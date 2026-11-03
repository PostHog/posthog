from datetime import date, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import PropertyDefinition
from posthog.test.persons import create_person

from products.access_control.backend.facade.api import upsert_property_access_control
from products.access_control.backend.facade.contracts import PropertyAccessLevel, UpsertPropertyAccessControlInput
from products.customer_analytics.backend.facade.api import get_key_metrics
from products.customer_analytics.backend.logic import key_metrics as key_metrics_logic


class TestKeyMetrics(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        blocking = patch.object(
            key_metrics_logic, "EXECUTION_MODE", ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        )
        blocking.start()
        self.addCleanup(blocking.stop)

    def _midnight(self) -> datetime:
        return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    @parameterized.expand(
        [
            ("an unrestricted viewer", False, [], {"signup_event": (7.0, 7.0), "activity_event": (2.0, 1.0)}),
            (
                "a viewer who cannot read the browser",
                True,
                [],
                {"signup_event": (0.0, 0.0), "activity_event": (2.0, 1.0)},
            ),
            (
                "a project that marks Chrome as a test account",
                False,
                [{"key": "$browser", "value": "Chrome", "operator": "is_not", "type": "event"}],
                {"signup_event": (0.0, 0.0), "activity_event": (1.0, 0.0)},
            ),
        ]
    )
    def test_key_metrics_count_filtered_events_and_weekly_unique_people(
        self,
        _name: str,
        restricted: bool,
        test_account_filters: list[dict[str, str]],
        expected: dict[str, tuple[float, float]],
    ) -> None:
        self.team.test_account_filters = test_account_filters
        self.team.save()
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        viewer = self._create_user("viewer@example.com")
        if restricted:
            definition = PropertyDefinition.objects.create(
                team=self.team, name="$browser", type=PropertyDefinition.Type.EVENT
            )
            upsert_property_access_control(
                team_id=self.team.id,
                created_by_id=None,
                input=UpsertPropertyAccessControlInput(
                    access_level=PropertyAccessLevel.NONE,
                    property_definition_id=str(definition.id),
                    organization_member_id=viewer.organization_memberships.get().id,
                ),
            )
        config = self.team.customer_analytics_config
        config.signup_event = {
            "kind": "EventsNode",
            "event": None,
            "properties": [{"key": "$browser", "value": "Chrome", "operator": "exact", "type": "event"}],
        }
        config.activity_event = {"kind": "EventsNode", "event": "opened_file"}
        config.payment_event = {"kind": "ActionsNode", "id": 999_999}
        config.save()
        for browser, days in (("Chrome", 20), ("Firefox", 7)):
            create_person(team=self.team, distinct_ids=[f"person-{browser}"])
            for day in range(1, days + 1):
                _create_event(
                    team=self.team,
                    event="opened_file",
                    distinct_id=f"person-{browser}",
                    properties={"$browser": browser},
                    timestamp=self._midnight() - timedelta(days=day) + timedelta(hours=12),
                )
        flush_persons_and_events()

        metrics = get_key_metrics(team=self.team, user=viewer)
        cached = get_key_metrics(team=self.team, user=viewer)
        assert metrics is not None

        self.assertEqual(
            (
                {m.key: (m.this_week, m.last_week) for m in metrics},
                {m.key: len(m.daily) for m in metrics},
                cached,
            ),
            (expected, {"signup_event": 35, "activity_event": 35}, metrics),
        )

    def test_days_follow_the_project_timezone(self) -> None:
        self.team.timezone = "Asia/Tokyo"
        self.team.save()
        config = self.team.customer_analytics_config
        config.activity_event = {"kind": "EventsNode", "event": "opened_file"}
        config.save()
        with time_machine.travel("2026-03-02T12:00:00Z", tick=False):
            for person, at in (("late-yesterday", "2026-03-01T14:00:00Z"), ("early-today", "2026-03-01T16:00:00Z")):
                create_person(team=self.team, distinct_ids=[person])
                _create_event(team=self.team, event="opened_file", distinct_id=person, timestamp=at)
            flush_persons_and_events()

            metrics = get_key_metrics(team=self.team, user=self.user)

        assert metrics is not None
        activity = metrics[0]
        self.assertEqual((activity.this_week, activity.daily[-1]), (1.0, (date(2026, 3, 1), 1.0)))

    @parameterized.expand([("activity_event", "opened_file", 2), ("signup_event", "signed_up", 1)])
    def test_uncached_queries_start_together_without_waiting_for_another_load(
        self, metric: str, event: str, queries: int
    ) -> None:
        config = self.team.customer_analytics_config
        for key in key_metrics_logic.KEY_METRICS:
            setattr(config, key, {})
        setattr(config, metric, {"kind": "EventsNode", "event": event})
        config.save()

        with (
            patch.object(key_metrics_logic, "EXECUTION_MODE", ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE),
            patch("posthog.hogql_queries.query_runner.QueryRunner.enqueue_async_calculation") as enqueue,
        ):
            metrics = get_key_metrics(team=self.team, user=self.user)

        self.assertEqual((metrics, enqueue.call_count), (None, queries))

    @parameterized.expand(
        [
            ("a later minute reuses the result", timedelta(minutes=10), True),
            ("a new day calculates again", timedelta(days=1), False),
        ]
    )
    def test_a_relative_date_filter_keeps_the_cached_result_until_the_day_changes(
        self, _name: str, later: timedelta, reused: bool
    ) -> None:
        self.team.test_account_filters = [
            {"key": "signed_up_at", "value": "-30d", "operator": "is_date_after", "type": "person"}
        ]
        self.team.save()
        config = self.team.customer_analytics_config
        config.activity_event = {
            "kind": "EventsNode",
            "event": "opened_file",
            "properties": [{"key": "opened_at", "value": "-7d", "operator": "is_date_after", "type": "event"}],
        }
        config.save()

        with time_machine.travel("2026-03-02T12:00:00Z", tick=False) as traveller:
            first = get_key_metrics(team=self.team, user=self.user)
            traveller.shift(later)
            with (
                patch.object(key_metrics_logic, "EXECUTION_MODE", ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE),
                patch("posthog.hogql_queries.query_runner.QueryRunner.enqueue_async_calculation"),
            ):
                second = get_key_metrics(team=self.team, user=self.user)

        assert first is not None
        self.assertEqual(
            (first[0].node["properties"][0]["value"], second == first),
            ("2026-02-23 00:00:00", reused),
        )
