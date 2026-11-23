import importlib
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest, TestMigrations
from unittest import mock

from django.apps import apps as django_apps
from django.db import connection
from django.test import override_settings

from posthog.models import Team

from products.cohorts.backend.backfill.finalize import FLAGS_CACHE_TASK
from products.cohorts.backend.models.cohort import Cohort

BEHAVIORAL_FILTERS = {
    "properties": {
        "type": "OR",
        "values": [
            {
                "type": "AND",
                "values": [
                    {"key": "$pageview", "type": "behavioral", "value": "performed_event", "event_type": "events"},
                    {"key": "email", "type": "person", "value": "x", "operator": "icontains"},
                ],
            }
        ],
    }
}
PERSON_FILTERS = {
    "properties": {"type": "AND", "values": [{"key": "email", "type": "person", "value": "x", "operator": "icontains"}]}
}
LIFECYCLE_FILTERS = {
    "properties": {
        "type": "AND",
        "values": [{"key": "signed_up", "type": "behavioral", "value": "performed_event_first_time"}],
    }
}
BEHAVIORAL_CONDITION_TYPE = {"person_properties": True, "behavioral": True, "lifecycle": False, "cohorts": False}
LIFECYCLE_CONDITION_TYPE = {"person_properties": False, "behavioral": False, "lifecycle": True, "cohorts": False}
STALE_CONDITION_TYPE = {"person_properties": True, "behavioral": False, "lifecycle": False, "cohorts": False}
STAMP = datetime(2026, 1, 1, tzinfo=UTC)


class TestBackfillCohortConditionType(TestMigrations):
    app = "cohorts"
    migrate_from = "0023_turn_on_realtime_for_processed_teams"
    migrate_to = "0024_backfill_cohort_condition_type"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Cohort = apps.get_model("cohorts", "Cohort")
        other_team = Team.objects.create(organization=self.organization, name="Other")

        def create(team_id: int = self.team.id, cohort_type: str = "realtime", **fields: Any) -> int:
            return Cohort.objects.create(team_id=team_id, cohort_type=cohort_type, **fields).id

        self.unclassified = create(filters=BEHAVIORAL_FILTERS, last_backfill_events_at=STAMP)
        self.unclassified_lifecycle = create(filters=LIFECYCLE_FILTERS, last_realtime_cohort_calculation_at=STAMP)
        self.unclassified_deleted = create(filters=BEHAVIORAL_FILTERS, deleted=True, last_backfill_events_at=STAMP)
        self.already_classified = create(filters=BEHAVIORAL_FILTERS, condition_type=STALE_CONDITION_TYPE)
        self.without_leaves = create(filters={"properties": {"type": "OR", "values": []}})
        self.without_filters = create(filters=None)
        self.unreadable = create(
            filters={"properties": {"type": "AND", "values": [{"type": "behavioral", "value": ["performed_event"]}]}}
        )
        create(team_id=other_team.id, filters=BEHAVIORAL_FILTERS)
        create(team_id=other_team.id, filters=PERSON_FILTERS, last_backfill_person_properties_at=STAMP)
        self.other_team_id = other_team.id
        stamped = {"team_id": other_team.id, "filters": BEHAVIORAL_FILTERS, "last_backfill_events_at": STAMP}
        create(cohort_type="behavioral", **stamped)
        create(cohort_type="behavioral", is_static=True, **stamped)
        create(cohort_type="analytical", **stamped)

        backfill = importlib.import_module("products.cohorts.backend.migrations.0024_backfill_cohort_condition_type")
        mock.patch.object(backfill, "BATCH_SIZE", 1).start()
        self.celery = mock.patch("products.cohorts.backend.backfill.finalize.current_app").start()
        self.addCleanup(mock.patch.stopall)
        flags_cache = override_settings(FLAGS_REDIS_URL="redis://localhost:6379/1")
        flags_cache.enable()
        self.addCleanup(flags_cache.disable)

    def test_classifies_only_the_cohorts_left_unclassified(self) -> None:
        Cohort = self.apps.get_model("cohorts", "Cohort")  # type: ignore[union-attr]
        condition_types = dict(Cohort.objects.filter(team_id=self.team.id).values_list("id", "condition_type"))

        assert condition_types == {
            self.unclassified: BEHAVIORAL_CONDITION_TYPE,
            self.unclassified_lifecycle: LIFECYCLE_CONDITION_TYPE,
            self.unclassified_deleted: BEHAVIORAL_CONDITION_TYPE,
            self.already_classified: STALE_CONDITION_TYPE,
            self.without_leaves: None,
            self.without_filters: None,
            self.unreadable: None,
        }

    def test_refreshes_the_flags_cache_only_where_routing_can_change(self) -> None:
        refresh = mock.call(FLAGS_CACHE_TASK, args=(self.team.id,), queue="feature_flags")
        refresh_other = mock.call(FLAGS_CACHE_TASK, args=(self.other_team_id,), queue="feature_flags")
        assert self.celery.send_task.call_args_list == [refresh, refresh, refresh_other]


@override_settings(FLAGS_REDIS_URL="redis://localhost:6379/1")
class TestBackfillAfterAStalledRefresh(BaseTest):
    def test_keeps_classifying_and_stops_refreshing(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        ids = [
            Cohort.objects.create(
                team=team, cohort_type="realtime", filters=BEHAVIORAL_FILTERS, last_backfill_events_at=STAMP
            ).id
            for team in (self.team, other_team)
        ]
        Cohort.objects.filter(id__in=ids).update(condition_type=None)

        release = threading.Event()
        self.addCleanup(release.set)
        refreshed: list[int] = []
        refresh_threads: list[threading.Thread] = []
        real_thread = threading.Thread

        def unanswered_refresh(team_id: int) -> None:
            refreshed.append(team_id)
            # Bounded, so that a refresh without a deadline fails the test instead of hanging it.
            release.wait(timeout=5)

        def tracked_thread(*args: Any, **kwargs: Any) -> threading.Thread:
            thread = real_thread(*args, **kwargs)
            refresh_threads.append(thread)
            return thread

        backfill = importlib.import_module("products.cohorts.backend.migrations.0024_backfill_cohort_condition_type")
        with (
            mock.patch.object(backfill, "BATCH_SIZE", 1),
            mock.patch.object(backfill, "REFRESH_DEADLINE_SECONDS", 0),
            mock.patch("products.cohorts.backend.backfill.finalize.refresh_readiness_caches", unanswered_refresh),
            mock.patch.object(backfill.threading, "Thread", tracked_thread),
        ):
            backfill.backfill_condition_type(django_apps, SimpleNamespace(connection=connection))
            # Every refresh the backfill started has to finish before `refreshed` says which teams it tried.
            release.set()
            for thread in refresh_threads:
                thread.join(timeout=5)

        assert refreshed == [self.team.id]
        assert list(Cohort.objects.filter(id__in=ids).order_by("id").values_list("condition_type", flat=True)) == [
            BEHAVIORAL_CONDITION_TYPE,
            BEHAVIORAL_CONDITION_TYPE,
        ]


class TestBackfillRacingASave(BaseTest):
    def test_keeps_the_value_a_concurrent_save_wrote(self) -> None:
        cohort = Cohort.objects.create(team=self.team, cohort_type="realtime", filters=BEHAVIORAL_FILTERS)
        Cohort.objects.filter(id=cohort.id).update(condition_type=None)
        classify = Cohort.compute_condition_type

        def classify_after_a_save(filters: Any) -> Any:
            Cohort.objects.filter(id=cohort.id).update(condition_type=LIFECYCLE_CONDITION_TYPE)
            return classify(filters)

        backfill = importlib.import_module("products.cohorts.backend.migrations.0024_backfill_cohort_condition_type")
        with mock.patch.object(Cohort, "compute_condition_type", side_effect=classify_after_a_save):
            backfill.backfill_condition_type(django_apps, SimpleNamespace(connection=connection))

        cohort.refresh_from_db()
        assert cohort.condition_type == LIFECYCLE_CONDITION_TYPE
