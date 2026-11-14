from datetime import UTC, datetime
from typing import Any

from posthog.test.base import TestMigrations
from unittest import mock

from django.test import override_settings

from posthog.models import Team

from products.cohorts.backend.backfill.finalize import FLAGS_CACHE_TASK

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
BEHAVIORAL_CONDITION_TYPE = {"person_properties": True, "behavioral": True, "lifecycle": False, "cohorts": False}
STALE_CONDITION_TYPE = {"person_properties": True, "behavioral": False, "lifecycle": False, "cohorts": False}
STAMP = datetime(2026, 1, 1, tzinfo=UTC)


class TestBackfillCohortConditionType(TestMigrations):
    app = "cohorts"
    migrate_from = "0021_cohort_backfill_refusal"
    migrate_to = "0024_backfill_cohort_condition_type"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Cohort = apps.get_model("cohorts", "Cohort")
        other_team = Team.objects.create(organization=self.organization, name="Other")

        def create(team_id: int = self.team.id, **fields: Any) -> int:
            return Cohort.objects.create(team_id=team_id, cohort_type="realtime", **fields).id

        self.unclassified = create(filters=BEHAVIORAL_FILTERS, last_backfill_events_at=STAMP)
        self.unclassified_deleted = create(filters=BEHAVIORAL_FILTERS, deleted=True)
        self.already_classified = create(filters=BEHAVIORAL_FILTERS, condition_type=STALE_CONDITION_TYPE)
        self.without_leaves = create(filters={"properties": {"type": "OR", "values": []}})
        self.without_filters = create(filters=None)
        self.unreadable = create(
            filters={"properties": {"type": "AND", "values": [{"type": "behavioral", "value": ["performed_event"]}]}}
        )
        create(team_id=other_team.id, filters=BEHAVIORAL_FILTERS)
        create(team_id=other_team.id, filters=PERSON_FILTERS, last_backfill_person_properties_at=STAMP)

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
            self.unclassified_deleted: BEHAVIORAL_CONDITION_TYPE,
            self.already_classified: STALE_CONDITION_TYPE,
            self.without_leaves: None,
            self.without_filters: None,
            self.unreadable: None,
        }

    def test_refreshes_the_flags_cache_only_where_routing_can_change(self) -> None:
        self.celery.send_task.assert_called_once_with(FLAGS_CACHE_TASK, args=(self.team.id,), queue="feature_flags")
