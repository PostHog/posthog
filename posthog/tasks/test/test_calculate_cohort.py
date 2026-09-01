from collections.abc import Callable
from typing import Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import InterfaceError, OperationalError
from django.test import override_settings
from django.utils import timezone

from celery.exceptions import Retry
from dateutil.relativedelta import relativedelta
from parameterized import parameterized

from posthog.hogql.errors import QueryError

from posthog.errors import CHQueryErrorQueryWasCancelled
from posthog.exceptions import ClickHouseAtCapacity
from posthog.tasks.calculate_cohort import (
    COHORT_BACKFILL_REFUSAL_OUTCOMES,
    COHORT_BACKFILL_TRIGGER_TASK_COUNTER,
    COHORT_RECALCULATION_MAX_RETRIES,
    COHORT_STUCK_COUNT_GAUGE,
    COHORTS_STALE_COUNT_GAUGE,
    COHORTS_TOTAL_GAUGE,
    MAX_AGE_MINUTES,
    MAX_ERRORS_CALCULATING,
    MAX_STUCK_COHORTS_TO_RESET,
    calculate_cohort_ch,
    calculate_cohort_from_list,
    enqueue_cohorts_to_calculate,
    increment_version_and_enqueue_calculate_cohort,
    insert_cohort_from_filters,
    reset_stuck_cohorts,
    trigger_cohort_backfill_run_task,
    update_cohort_metrics,
)
from posthog.test.persons import create_person

from products.cohorts.backend.backfill.runs import BackfillRefusalReason
from products.cohorts.backend.backfill.sizing import PersonSeedEstimate
from products.cohorts.backend.models.backfill import CohortBackfillKind, CohortBackfillRun
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.util import count_cohort_members, list_cohort_member_ids

MISSING_COHORT_ID = 12345

BACKFILL_KINDS = [("behavioral", CohortBackfillKind.BEHAVIORAL), ("person", CohortBackfillKind.PERSON_PROPERTY)]

# What the task needs to reach the creators: both allowlists open, every attestation the two kinds
# check between them, and a person seed budget. Tests peel these back to exercise the guards.
BACKFILL_TASK_SETTINGS = {
    "REALTIME_COHORT_TEAM_ALLOWLIST": "all",
    "COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST": "all",
    "BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED": True,
    "BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED": True,
    "BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED": True,
    "BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED": True,
    "BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET": 1_000_000,
}


def calculate_cohort_test_factory(event_factory: Callable, person_factory: Callable):  # type: ignore
    class TestCalculateCohort(APIBaseTest):
        @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
        def test_create_stickiness_cohort(self, _calculate_cohort_from_list: MagicMock) -> None:
            person_factory(team_id=self.team.pk, distinct_ids=["blabla"])
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="blabla",
                properties={"$math_prop": 1},
                timestamp="2021-01-01T12:00:00Z",
            )
            response = self.client.post(
                f"/api/projects/{self.team.id}/cohorts/?insight=STICKINESS&properties=%5B%5D&interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&shown_as=Stickiness&date_from=2021-01-01&entity_id=%24pageview&entity_type=events&stickiness_days=1&label=%24pageview",
                {"name": "test", "is_static": True},
            ).json()

            cohort_id = response["id"]
            _calculate_cohort_from_list.assert_called_once_with(cohort_id, ["blabla"])
            calculate_cohort_from_list(cohort_id, ["blabla"], team_id=self.team.id, id_type="distinct_id")
            cohort = Cohort.objects.get(pk=cohort_id)
            self.assertEqual(count_cohort_members(cohort.team_id, cohort.pk), 1)

        @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
        def test_create_trends_cohort(self, _calculate_cohort_from_list: MagicMock) -> None:
            person_factory(team_id=self.team.pk, distinct_ids=["blabla"])
            with freeze_time("2021-01-01 00:06:34"):
                event_factory(
                    team=self.team,
                    event="$pageview",
                    distinct_id="blabla",
                    properties={"$math_prop": 1},
                    timestamp="2021-01-01T12:00:00Z",
                )

            with freeze_time("2021-01-02 00:06:34"):
                event_factory(
                    team=self.team,
                    event="$pageview",
                    distinct_id="blabla",
                    properties={"$math_prop": 4},
                    timestamp="2021-01-01T12:00:00Z",
                )

            response = self.client.post(
                f"/api/projects/{self.team.id}/cohorts/?interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&properties=%5B%5D&entity_id=%24pageview&entity_type=events&date_from=2021-01-01&date_to=2021-01-01&label=%24pageview",
                {"name": "test", "is_static": True},
            ).json()
            cohort_id = response["id"]
            _calculate_cohort_from_list.assert_called_once_with(cohort_id, ["blabla"])
            calculate_cohort_from_list(cohort_id, ["blabla"], team_id=self.team.id, id_type="distinct_id")
            cohort = Cohort.objects.get(pk=cohort_id)
            self.assertEqual(count_cohort_members(cohort.team_id, cohort.pk), 1)

        def test_calculate_cohort_from_list_with_person_id_type(self) -> None:
            """Test that calculate_cohort_from_list works correctly with person UUIDs"""
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["user123"])
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["user456"])

            cohort = Cohort.objects.create(team=self.team, is_static=True, name="test_person_id_cohort")

            # Test with person UUIDs
            calculate_cohort_from_list(
                cohort.id,
                [str(person1.uuid), str(person2.uuid)],
                team_id=self.team.id,
                id_type="person_id",
            )

            # Verify persons were added to cohort
            cohort.refresh_from_db()
            self.assertEqual(count_cohort_members(cohort.team_id, cohort.pk), 2)

            # Verify specific persons are in the cohort
            member_ids = set(list_cohort_member_ids(team_id=cohort.team_id, cohort_id=cohort.pk))
            self.assertIn(person1.id, member_ids)
            self.assertIn(person2.id, member_ids)

        def test_calculate_cohort_from_list_with_distinct_id_type(self) -> None:
            """Test that calculate_cohort_from_list works correctly with distinct IDs"""
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["user123"])
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["user456"])

            cohort = Cohort.objects.create(team=self.team, is_static=True, name="test_distinct_id_cohort")

            # Test with distinct IDs
            calculate_cohort_from_list(
                cohort.id,
                ["user123", "user456"],
                team_id=self.team.id,
                id_type="distinct_id",
            )

            # Verify persons were added to cohort
            cohort.refresh_from_db()
            self.assertEqual(count_cohort_members(cohort.team_id, cohort.pk), 2)

            # Verify specific persons are in the cohort
            member_ids = set(list_cohort_member_ids(team_id=cohort.team_id, cohort_id=cohort.pk))
            self.assertIn(person1.id, member_ids)
            self.assertIn(person2.id, member_ids)

        @patch("posthog.tasks.calculate_cohort.increment_version_and_enqueue_calculate_cohort")
        def test_exponential_backoff(self, patch_increment_version_and_enqueue_calculate_cohort: MagicMock) -> None:
            # Exponential backoff
            Cohort.objects.create(
                last_calculation=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES + 1),
                errors_calculating=1,
                last_error_at=timezone.now() - relativedelta(minutes=60),  # Should be included
                team_id=self.team.pk,
            )
            Cohort.objects.create(
                last_calculation=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES + 1),
                errors_calculating=5,
                last_error_at=timezone.now() - relativedelta(minutes=60),  # Should be excluded
                team_id=self.team.pk,
            )
            # Test empty last_error_at
            Cohort.objects.create(
                last_calculation=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES + 1),
                errors_calculating=1,
                team_id=self.team.pk,
            )
            enqueue_cohorts_to_calculate(5)
            self.assertEqual(patch_increment_version_and_enqueue_calculate_cohort.call_count, 2)

        @patch.object(COHORTS_TOTAL_GAUGE, "set")
        @patch.object(COHORTS_STALE_COUNT_GAUGE, "labels")
        def test_update_stale_cohort_metrics(self, mock_labels: MagicMock, mock_total_set: MagicMock) -> None:
            mock_gauge = MagicMock()
            mock_labels.return_value = mock_gauge

            now = timezone.now()

            # Create cohorts with different staleness levels
            Cohort.objects.create(
                team_id=self.team.pk,
                name="fresh_cohort",
                last_calculation=now - relativedelta(hours=12),  # Not stale
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="stale_24h",
                last_calculation=now - relativedelta(hours=30),  # Stale for 24h
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="stale_36h",
                last_calculation=now - relativedelta(hours=40),  # Stale for 36h
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="stale_48h",
                last_calculation=now - relativedelta(hours=50),  # Stale for 48h
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            # Create cohorts that should be excluded
            Cohort.objects.create(
                team_id=self.team.pk,
                name="null_last_calc",  # Should be excluded
                last_calculation=None,
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="deleted_cohort",
                last_calculation=now - relativedelta(hours=50),
                deleted=True,  # Should be excluded
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="static_cohort",
                last_calculation=now - relativedelta(hours=50),
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=True,  # Should be excluded
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="high_errors",
                last_calculation=now - relativedelta(hours=50),
                deleted=False,
                is_calculating=False,
                errors_calculating=MAX_ERRORS_CALCULATING + 1,  # Should be excluded (>20 errors)
                is_static=False,
            )

            update_cohort_metrics()

            mock_labels.assert_any_call(hours="24")
            mock_labels.assert_any_call(hours="36")
            mock_labels.assert_any_call(hours="48")

            set_calls = mock_gauge.set.call_args_list
            self.assertEqual(len(set_calls), 3)

            self.assertEqual(set_calls[0][0][0], 3)  # 24h: stale_24h, stale_36h, stale_48h
            self.assertEqual(set_calls[1][0][0], 2)  # 36h: stale_36h, stale_48h
            self.assertEqual(set_calls[2][0][0], 1)  # 48h: stale_48h

            # 4 eligible cohorts: fresh_cohort, stale_24h, stale_36h, stale_48h
            # Excluded: null_last_calc (no last_calculation), deleted_cohort, static_cohort, high_errors
            mock_total_set.assert_called_once_with(4)

        @patch.object(COHORT_STUCK_COUNT_GAUGE, "set")
        def test_stuck_cohort_metrics(self, mock_set: MagicMock) -> None:
            now = timezone.now()

            # Create stuck cohort - is_calculating=True and last_calculation > 12 hours ago
            Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_cohort",
                last_calculation=now - relativedelta(hours=2),
                deleted=False,
                is_calculating=True,  # Stuck calculating
                errors_calculating=5,
                is_static=False,
            )

            # Create another stuck cohort
            Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_cohort_2",
                last_calculation=now - relativedelta(hours=3),
                deleted=False,
                is_calculating=True,  # Stuck calculating
                errors_calculating=2,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="not_calculating",
                last_calculation=now - relativedelta(hours=24),  # Old but not calculating
                deleted=False,
                is_calculating=False,  # Not calculating
                errors_calculating=0,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="recent_calculation",
                last_calculation=now - relativedelta(minutes=59),  # Recent calculation
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=False,
            )

            update_cohort_metrics()
            mock_set.assert_called_with(2)

        @patch("posthog.tasks.calculate_cohort.logger")
        def test_reset_stuck_cohorts(self, mock_logger: MagicMock) -> None:
            now = timezone.now()

            # Create stuck cohorts that should be reset (is_calculating=True, last_calculation > 24 hours ago)
            stuck_cohort_1 = Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_cohort_1",
                last_calculation=now - relativedelta(hours=25),  # Stuck for 25 hours
                deleted=False,
                is_calculating=True,
                errors_calculating=2,
                is_static=False,
            )

            stuck_cohort_2 = Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_cohort_2",
                last_calculation=now - relativedelta(hours=48),  # Stuck for 48 hours
                deleted=False,
                is_calculating=True,
                errors_calculating=1,
                is_static=False,
            )

            # Create cohorts that should NOT be reset
            # Not stuck (recent calculation)
            not_stuck_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="not_stuck_cohort",
                last_calculation=now - relativedelta(minutes=10),  # Recent calculation
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=False,
            )

            # Static cohort (should be excluded)
            static_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="static_cohort",
                last_calculation=now - relativedelta(hours=48),
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=True,  # Static cohorts are excluded
            )

            # Deleted cohort (should be excluded)
            deleted_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="deleted_cohort",
                last_calculation=now - relativedelta(hours=48),
                deleted=True,  # Deleted cohorts are excluded
                is_calculating=True,
                errors_calculating=0,
                is_static=False,
            )

            # Cohort with null last_calculation (should be excluded)
            null_last_calc_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="null_last_calc_cohort",
                last_calculation=None,  # Null last_calculation is excluded
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=False,
            )

            # Not calculating cohort (should be excluded)
            not_calculating_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="not_calculating_cohort",
                last_calculation=now - relativedelta(hours=48),
                deleted=False,
                is_calculating=False,  # Not calculating
                errors_calculating=0,
                is_static=False,
            )

            # Run the function
            reset_stuck_cohorts()

            # Verify that stuck cohorts were reset
            stuck_cohort_1.refresh_from_db()
            stuck_cohort_2.refresh_from_db()
            self.assertFalse(stuck_cohort_1.is_calculating)
            self.assertFalse(stuck_cohort_2.is_calculating)

            # Verify that non-stuck cohorts were NOT reset
            not_stuck_cohort.refresh_from_db()
            static_cohort.refresh_from_db()
            deleted_cohort.refresh_from_db()
            null_last_calc_cohort.refresh_from_db()
            not_calculating_cohort.refresh_from_db()

            self.assertTrue(not_stuck_cohort.is_calculating)  # Should still be calculating
            self.assertFalse(static_cohort.is_calculating)  # Static cohorts are now also reset
            self.assertTrue(deleted_cohort.is_calculating)  # Should still be calculating
            self.assertTrue(null_last_calc_cohort.is_calculating)  # Should still be calculating
            self.assertFalse(not_calculating_cohort.is_calculating)  # Should remain not calculating

            # Verify logging - both dynamic and static resets are logged
            warning_calls = mock_logger.warning.call_args_list
            dynamic_reset_call = [c for c in warning_calls if c[0][0] == "reset_stuck_cohorts"]
            self.assertEqual(len(dynamic_reset_call), 1)
            self.assertEqual(
                set(dynamic_reset_call[0][1]["cohort_ids"]),
                {stuck_cohort_1.pk, stuck_cohort_2.pk},
            )

            static_reset_call = [c for c in warning_calls if c[0][0] == "reset_stuck_static_cohorts"]
            self.assertEqual(len(static_reset_call), 1)
            self.assertIn(static_cohort.pk, static_reset_call[0][1]["cohort_ids"])

        @patch("posthog.tasks.calculate_cohort.logger")
        def test_reset_stuck_cohorts_respects_limit(self, mock_logger: MagicMock) -> None:
            now = timezone.now()

            # Create more stuck cohorts than the limit (MAX_STUCK_COHORTS_TO_RESET)
            stuck_cohorts = []
            for i in range(MAX_STUCK_COHORTS_TO_RESET + 3):
                cohort = Cohort.objects.create(
                    team_id=self.team.pk,
                    name=f"stuck_cohort_{i}",
                    last_calculation=now - relativedelta(hours=25),
                    deleted=False,
                    is_calculating=True,
                    errors_calculating=0,
                    is_static=False,
                )
                stuck_cohorts.append(cohort)

            reset_stuck_cohorts()

            # Count how many were actually reset
            reset_count = 0
            for cohort in stuck_cohorts:
                cohort.refresh_from_db()
                if not cohort.is_calculating:
                    reset_count += 1

            self.assertEqual(reset_count, MAX_STUCK_COHORTS_TO_RESET)

            # Verify logging
            warning_calls = mock_logger.warning.call_args_list
            dynamic_reset_calls = [c for c in warning_calls if c[0][0] == "reset_stuck_cohorts"]
            self.assertEqual(len(dynamic_reset_calls), 1)
            self.assertEqual(len(dynamic_reset_calls[0][1]["cohort_ids"]), MAX_STUCK_COHORTS_TO_RESET)
            self.assertEqual(dynamic_reset_calls[0][1]["count"], MAX_STUCK_COHORTS_TO_RESET)

        @patch("posthog.tasks.calculate_cohort.insert_cohort_from_query")
        @patch("posthog.tasks.calculate_cohort.logger")
        def test_reset_stuck_static_cohorts_retriggers_query(
            self, mock_logger: MagicMock, mock_insert_cohort_from_query: MagicMock
        ) -> None:
            now = timezone.now()

            # Create a stuck static cohort with a query, null last_calculation, created > 1 hour ago
            stuck_static_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_static_with_query",
                last_calculation=None,
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=True,
                query={
                    "kind": "HogQLQuery",
                    "query": "SELECT person_id FROM cohort_people WHERE cohort_id = 123",
                },
            )
            # Set created_at to more than 1 hour ago (auto_now_add prevents setting on create)
            Cohort.objects.filter(pk=stuck_static_cohort.pk).update(created_at=now - relativedelta(hours=2))

            reset_stuck_cohorts()

            stuck_static_cohort.refresh_from_db()
            self.assertFalse(stuck_static_cohort.is_calculating)
            self.assertEqual(stuck_static_cohort.errors_calculating, 1)

            # Verify insert_cohort_from_query was re-dispatched
            mock_insert_cohort_from_query.delay.assert_called_with(stuck_static_cohort.pk, self.team.pk)

        @patch("posthog.tasks.calculate_cohort.insert_cohort_from_query")
        @patch("posthog.tasks.calculate_cohort.logger")
        def test_reset_stuck_static_cohorts_stops_after_max_errors(
            self, mock_logger: MagicMock, mock_insert_cohort_from_query: MagicMock
        ) -> None:
            now = timezone.now()

            # Create a stuck static cohort that has already hit MAX_ERRORS_CALCULATING
            stuck_static_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_static_max_errors",
                last_calculation=None,
                deleted=False,
                is_calculating=True,
                errors_calculating=MAX_ERRORS_CALCULATING,
                is_static=True,
                query={
                    "kind": "HogQLQuery",
                    "query": "SELECT person_id FROM cohort_people WHERE cohort_id = 123",
                },
            )
            # Set created_at to more than 1 hour ago
            Cohort.objects.filter(pk=stuck_static_cohort.pk).update(created_at=now - relativedelta(hours=2))

            reset_stuck_cohorts()

            stuck_static_cohort.refresh_from_db()
            # Should NOT be picked up because errors_calculating is at the max
            self.assertTrue(stuck_static_cohort.is_calculating)

            # Verify insert_cohort_from_query was NOT called
            mock_insert_cohort_from_query.delay.assert_not_called()

        @patch("posthog.tasks.calculate_cohort.insert_cohort_from_filters")
        @patch("posthog.tasks.calculate_cohort.logger")
        def test_reset_stuck_static_cohorts_retriggers_filters(
            self, mock_logger: MagicMock, mock_insert_cohort_from_filters: MagicMock
        ) -> None:
            now = timezone.now()

            stuck_static_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_static_with_filters",
                last_calculation=None,
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=True,
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [{"key": "email", "type": "person", "value": "match@example.com"}],
                            }
                        ],
                    }
                },
            )
            Cohort.objects.filter(pk=stuck_static_cohort.pk).update(created_at=now - relativedelta(hours=2))

            reset_stuck_cohorts()

            stuck_static_cohort.refresh_from_db()
            self.assertFalse(stuck_static_cohort.is_calculating)
            self.assertEqual(stuck_static_cohort.errors_calculating, 1)
            mock_insert_cohort_from_filters.delay.assert_called_with(stuck_static_cohort.pk, self.team.pk)

        @patch("posthog.tasks.calculate_cohort.insert_cohort_from_query")
        @patch("posthog.tasks.calculate_cohort.insert_cohort_from_filters")
        @patch("posthog.tasks.calculate_cohort.logger")
        def test_reset_stuck_static_cohorts_without_retriggerable_source(
            self,
            mock_logger: MagicMock,
            mock_insert_cohort_from_filters: MagicMock,
            mock_insert_cohort_from_query: MagicMock,
        ) -> None:
            now = timezone.now()

            stuck_static_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_static_without_source",
                last_calculation=None,
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=True,
                filters={"properties": {}},
            )
            Cohort.objects.filter(pk=stuck_static_cohort.pk).update(created_at=now - relativedelta(hours=2))

            reset_stuck_cohorts()

            stuck_static_cohort.refresh_from_db()
            self.assertFalse(stuck_static_cohort.is_calculating)
            self.assertEqual(stuck_static_cohort.errors_calculating, 1)
            mock_insert_cohort_from_filters.delay.assert_not_called()
            mock_insert_cohort_from_query.delay.assert_not_called()

        @patch("posthog.tasks.calculate_cohort.increment_version_and_enqueue_calculate_cohort")
        @patch("posthog.tasks.calculate_cohort.logger")
        def test_enqueue_cohorts_logs_correctly(self, mock_logger: MagicMock, mock_increment: MagicMock) -> None:
            # Create cohorts that will be selected for calculation
            last_calc_time = timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES + 1)
            cohort1 = Cohort.objects.create(
                team_id=self.team.pk,
                name="test_cohort_1",
                last_calculation=last_calc_time,
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )
            cohort2 = Cohort.objects.create(
                team_id=self.team.pk,
                name="test_cohort_2",
                last_calculation=None,  # Never calculated
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            enqueue_cohorts_to_calculate(2)

            self.assertEqual(mock_logger.warning.call_count, 1)
            args, kwargs = mock_logger.warning.call_args
            assert args[0] == "enqueued_cohort_calculation"
            assert set(kwargs["cohort_ids"]) == {cohort1.pk, cohort2.pk}

        @patch("posthog.tasks.calculate_cohort.chain")
        @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
        def test_increment_version_and_enqueue_calculate_cohort_with_nested_cohorts(
            self, mock_calculate_cohort_ch_si: MagicMock, mock_chain: MagicMock
        ) -> None:
            # Test dependency graph structure:
            # A ──┐
            #     ├─→ C ──→ D
            # B ──┘
            # Expected execution order: A, B, C, D

            # Create leaf cohort A
            cohort_a = Cohort.objects.create(
                team=self.team,
                name="Cohort A",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$some_prop_a",
                                "value": "something_a",
                                "type": "person",
                            }
                        ],
                    }
                },
                is_static=False,
            )

            # Create leaf cohort B
            cohort_b = Cohort.objects.create(
                team=self.team,
                name="Cohort B",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$some_prop_b",
                                "value": "something_b",
                                "type": "person",
                            }
                        ],
                    }
                },
                is_static=False,
            )

            # Create cohort C that depends on both cohort A and B
            cohort_c = Cohort.objects.create(
                team=self.team,
                name="Cohort C",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"key": "id", "value": cohort_a.id, "type": "cohort"},
                            {"key": "id", "value": cohort_b.id, "type": "cohort"},
                        ],
                    }
                },
                is_static=False,
            )

            # Create cohort D that depends on cohort C
            cohort_d = Cohort.objects.create(
                team=self.team,
                name="Cohort D",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [{"key": "id", "value": cohort_c.id, "type": "cohort"}],
                    }
                },
                is_static=False,
            )

            mock_chain_instance = MagicMock()
            mock_chain.return_value = mock_chain_instance

            mock_task = MagicMock()
            mock_calculate_cohort_ch_si.return_value = mock_task

            increment_version_and_enqueue_calculate_cohort(cohort_d, initiating_user=None)

            # Verify that all cohorts have their versions incremented and are marked as calculating
            cohort_a.refresh_from_db()
            cohort_b.refresh_from_db()
            cohort_c.refresh_from_db()
            cohort_d.refresh_from_db()

            self.assertEqual(cohort_a.pending_version, 1)
            self.assertEqual(cohort_b.pending_version, 1)
            self.assertEqual(cohort_c.pending_version, 1)
            self.assertEqual(cohort_d.pending_version, 1)
            self.assertTrue(cohort_a.is_calculating)
            self.assertTrue(cohort_b.is_calculating)
            self.assertTrue(cohort_c.is_calculating)
            self.assertTrue(cohort_d.is_calculating)

            self.assertEqual(mock_calculate_cohort_ch_si.call_count, 4)

            # Extract the actual call order and verify dependency constraints are satisfied
            actual_calls = mock_calculate_cohort_ch_si.call_args_list
            actual_cohort_order = [call[0][0] for call in actual_calls]  # Extract cohort IDs

            self.assertEqual(
                set(actual_cohort_order),
                {cohort_a.id, cohort_b.id, cohort_c.id, cohort_d.id},
            )

            # Verify dependency constraints:
            # Both A and B (leaf nodes) must come before C
            a_index = actual_cohort_order.index(cohort_a.id)
            b_index = actual_cohort_order.index(cohort_b.id)
            c_index = actual_cohort_order.index(cohort_c.id)
            d_index = actual_cohort_order.index(cohort_d.id)

            self.assertLess(a_index, c_index, "Cohort A must be processed before C (dependency)")
            self.assertLess(b_index, c_index, "Cohort B must be processed before C (dependency)")
            self.assertLess(c_index, d_index, "Cohort C must be processed before D (dependency)")

            # Verify countdown: first task has no countdown, all subsequent have countdown=2
            # mock_calculate_cohort_ch_si returns mock_task, and .set() is called on it for non-first tasks
            set_calls = mock_task.set.call_args_list
            self.assertEqual(len(set_calls), 3, "3 of 4 tasks should have .set(countdown=2) called")
            for call in set_calls:
                self.assertEqual(call, ((), {"countdown": 2}))

            mock_chain.assert_called_once()
            mock_chain_instance.apply_async.assert_called_once()

        @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
        def test_increment_version_and_enqueue_single_cohort_has_no_countdown(
            self, mock_calculate_cohort_ch_delay: MagicMock
        ) -> None:
            cohort = Cohort.objects.create(
                team=self.team,
                name="Standalone Cohort",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            }
                        ],
                    }
                },
                is_static=False,
            )

            increment_version_and_enqueue_calculate_cohort(cohort, initiating_user=None)

            mock_calculate_cohort_ch_delay.assert_called_once()
            call_args = mock_calculate_cohort_ch_delay.call_args[0]
            self.assertEqual(
                len(call_args),
                3,
                "Single cohort path should use .delay() with no countdown",
            )

        @patch("posthog.tasks.calculate_cohort.chain")
        @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
        def test_increment_version_and_enqueue_calculate_cohort_with_missing_cohort(
            self, mock_calculate_cohort_ch_si: MagicMock, mock_chain: MagicMock
        ) -> None:
            cohort_a = Cohort.objects.create(
                team=self.team,
                name="Cohort A",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$some_prop_a",
                                "value": "something_a",
                                "type": "person",
                            }
                        ],
                    }
                },
                is_static=False,
            )

            # Create a cohort that references a non-existent cohort ID
            cohort_with_missing_dependency = Cohort.objects.create(
                team=self.team,
                name="Cohort with missing dependency",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "key": "id",
                                "value": MISSING_COHORT_ID,
                                "type": "cohort",
                            },  # non-existent cohort
                            {"key": "id", "value": cohort_a.id, "type": "cohort"},
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            },
                        ],
                    }
                },
                is_static=False,
            )

            mock_chain_instance = MagicMock()
            mock_chain.return_value = mock_chain_instance

            mock_task = MagicMock()
            mock_calculate_cohort_ch_si.return_value = mock_task

            increment_version_and_enqueue_calculate_cohort(cohort_with_missing_dependency, initiating_user=None)

            # Verify the cohort was still processed despite missing dependency
            cohort_with_missing_dependency.refresh_from_db()
            cohort_a.refresh_from_db()
            self.assertEqual(cohort_with_missing_dependency.pending_version, 1)
            self.assertEqual(cohort_a.pending_version, 1)
            self.assertTrue(cohort_with_missing_dependency.is_calculating)
            self.assertTrue(cohort_a.is_calculating)

            self.assertEqual(mock_calculate_cohort_ch_si.call_count, 2)

            # Extract the actual call order and verify dependency cohort comes first
            actual_calls = mock_calculate_cohort_ch_si.call_args_list
            actual_cohort_order = [call[0][0] for call in actual_calls]  # Extract cohort IDs
            expected_cohort_order = [cohort_a.id, cohort_with_missing_dependency.id]

            self.assertEqual(
                actual_cohort_order,
                expected_cohort_order,
                "Dependency cohort A should be processed before cohort with missing dependency",
            )

            mock_chain.assert_called_once_with(mock_task, mock_task)
            mock_chain_instance.apply_async.assert_called_once()

        @patch("posthog.tasks.calculate_cohort.chain")
        @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
        def test_increment_version_and_enqueue_calculate_cohort_with_static_dependencies(
            self, mock_calculate_cohort_ch_si: MagicMock, mock_chain: MagicMock
        ) -> None:
            static_cohort_a = Cohort.objects.create(
                team=self.team,
                name="Static Cohort A",
                is_static=True,
            )

            dynamic_cohort = Cohort.objects.create(
                team=self.team,
                name="Dynamic Cohort depending on static cohorts",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "key": "id",
                                "value": static_cohort_a.id,
                                "type": "cohort",
                            },
                            {
                                "key": "$dynamic_prop",
                                "value": "dynamic_value",
                                "type": "person",
                            },
                        ],
                    }
                },
                is_static=False,
            )

            mock_chain_instance = MagicMock()
            mock_chain.return_value = mock_chain_instance

            mock_task = MagicMock()
            mock_calculate_cohort_ch_si.return_value = mock_task

            increment_version_and_enqueue_calculate_cohort(dynamic_cohort, initiating_user=None)

            static_cohort_a.refresh_from_db()
            dynamic_cohort.refresh_from_db()

            self.assertEqual(static_cohort_a.pending_version, None)
            self.assertFalse(static_cohort_a.is_calculating)

            self.assertEqual(dynamic_cohort.pending_version, 1)
            self.assertTrue(dynamic_cohort.is_calculating)

            # Only one task should be created (for the dynamic cohort)
            self.assertEqual(mock_calculate_cohort_ch_si.call_count, 1)

            # Verify the dynamic cohort was called
            actual_calls = mock_calculate_cohort_ch_si.call_args_list
            actual_cohort_order = [call[0][0] for call in actual_calls]
            expected_cohort_order = [dynamic_cohort.id]

            self.assertEqual(
                actual_cohort_order,
                expected_cohort_order,
                "Only the dynamic cohort should be processed, static dependencies are skipped",
            )

            mock_chain.assert_called_once_with(mock_task)
            mock_chain_instance.apply_async.assert_called_once()

        @patch("posthog.tasks.calculate_cohort.chain")
        @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
        def test_increment_version_and_enqueue_calculate_cohort_with_cyclic_dependency(
            self, mock_calculate_cohort_ch_si: MagicMock, mock_chain: MagicMock
        ) -> None:
            # Create a cyclic dependency: A -> B -> C -> A
            cohort_a = Cohort.objects.create(
                team=self.team,
                name="Cohort A",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$some_prop_a",
                                "value": "something_a",
                                "type": "person",
                            }
                        ],
                    }
                },
                is_static=False,
            )

            cohort_b = Cohort.objects.create(
                team=self.team,
                name="Cohort B",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"key": "id", "value": cohort_a.id, "type": "cohort"},
                            {
                                "key": "$some_prop_b",
                                "value": "something_b",
                                "type": "person",
                            },
                        ],
                    }
                },
                is_static=False,
            )

            cohort_c = Cohort.objects.create(
                team=self.team,
                name="Cohort C",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"key": "id", "value": cohort_b.id, "type": "cohort"},
                            {
                                "key": "$some_prop_c",
                                "value": "something_c",
                                "type": "person",
                            },
                        ],
                    }
                },
                is_static=False,
            )

            # Create the cycle by making A depend on C
            cohort_a.filters = {
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "id", "value": cohort_c.id, "type": "cohort"},
                        {
                            "key": "$some_prop_a",
                            "value": "something_a",
                            "type": "person",
                        },
                    ],
                }
            }
            cohort_a.save()

            mock_chain_instance = MagicMock()
            mock_chain.return_value = mock_chain_instance

            mock_task = MagicMock()
            mock_calculate_cohort_ch_si.return_value = mock_task

            increment_version_and_enqueue_calculate_cohort(cohort_a, initiating_user=None)

            cohort_a.refresh_from_db()
            cohort_b.refresh_from_db()
            cohort_c.refresh_from_db()

            self.assertEqual(cohort_a.pending_version, 1)
            self.assertEqual(cohort_b.pending_version, 1)
            self.assertEqual(cohort_c.pending_version, 1)
            self.assertTrue(cohort_a.is_calculating)
            self.assertTrue(cohort_b.is_calculating)
            self.assertTrue(cohort_c.is_calculating)

            self.assertEqual(mock_calculate_cohort_ch_si.call_count, 3)

            actual_calls = mock_calculate_cohort_ch_si.call_args_list
            actual_cohort_order = [call[0][0] for call in actual_calls]

            self.assertEqual(len(actual_cohort_order), 3)
            self.assertEqual(len(set(actual_cohort_order)), 3)

            mock_chain.assert_called_once_with(mock_task, mock_task, mock_task)
            mock_chain_instance.apply_async.assert_called_once()

    return TestCalculateCohort


class TestCohortCalculationTasks(APIBaseTest):
    def _backfillable_cohort(self) -> Cohort:
        return Cohort.objects.create(
            team=self.team,
            name="backfill trigger",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "event_type": "events",
                            "value": "performed_event",
                            "conditionHash": "behavior00000001",
                            "time_value": 7,
                            "time_interval": "day",
                        },
                        {
                            "type": "person",
                            "key": "email",
                            "value": ["person@example.com"],
                            "operator": "exact",
                            "conditionHash": "person0000000001",
                        },
                    ],
                }
            },
        )

    @parameterized.expand(BACKFILL_KINDS)
    @override_settings(**BACKFILL_TASK_SETTINGS)
    def test_trigger_backfill_run_task_returns_quietly_when_the_run_is_refused(
        self, _name: str, backfill_kind: CohortBackfillKind
    ) -> None:
        # The cohort can be deleted or edited into ineligibility during the debounce window, and
        # then the creator refuses. Raising there would spend the task's retries re-deciding the
        # same refusal. The allowlists and attestations are open here so the refusal under test is
        # the creator's own, not an earlier guard's.
        trigger_cohort_backfill_run_task(self.team.pk, MISSING_COHORT_ID, "cohort_edited", backfill_kind.value)

        self.assertFalse(CohortBackfillRun.objects.for_team(self.team.pk).exists())

    @parameterized.expand(BACKFILL_KINDS)
    def test_trigger_backfill_run_task_creates_a_run_of_the_requested_kind(
        self, _name: str, backfill_kind: CohortBackfillKind
    ) -> None:
        # The worker receives the kind as a plain string after JSON serialization, and the task's
        # branch on it picks the creator. A person trigger that filed a behavioral run would leave
        # the person conditions unseeded with nothing going red.
        cohort = self._backfillable_cohort()

        with override_settings(**BACKFILL_TASK_SETTINGS):
            trigger_cohort_backfill_run_task(self.team.pk, cohort.pk, "cohort_created", backfill_kind.value)

        run = CohortBackfillRun.objects.for_team(self.team.pk).get()
        self.assertEqual(run.backfill_kind, backfill_kind)
        self.assertEqual(run.cohort_id, cohort.pk)

    @parameterized.expand(BACKFILL_KINDS)
    def test_trigger_backfill_run_task_skips_instead_of_parking_a_blocked_run(
        self, _name: str, backfill_kind: CohortBackfillKind
    ) -> None:
        # With the attestations unset the creators would record a `blocked` row, which counts as
        # active, occupies the per-cohort uniqueness slot, and nothing ever advances. A team opted
        # into the trigger allowlist before the operator attests would wedge every cohort it saves.
        cohort = self._backfillable_cohort()

        with override_settings(REALTIME_COHORT_TEAM_ALLOWLIST="all", COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="all"):
            trigger_cohort_backfill_run_task(self.team.pk, cohort.pk, "cohort_created", backfill_kind.value)

        self.assertFalse(CohortBackfillRun.objects.for_team(self.team.pk).exists())

    def test_trigger_backfill_run_task_skips_when_the_person_budget_is_unset(self) -> None:
        # All four attestations on but no byte budget: `over_budget` is a strict comparison against
        # it, so every sized run would refuse, after paying for a full-team sizing scan each time.
        # The precondition check has to catch this before the scan.
        cohort = self._backfillable_cohort()

        with (
            override_settings(**{**BACKFILL_TASK_SETTINGS, "BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET": 0}),
            patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes") as estimate,
        ):
            trigger_cohort_backfill_run_task(
                self.team.pk, cohort.pk, "cohort_created", CohortBackfillKind.PERSON_PROPERTY.value
            )

        estimate.assert_not_called()
        self.assertFalse(CohortBackfillRun.objects.for_team(self.team.pk).exists())

    def test_trigger_backfill_run_task_labels_a_budget_refusal_apart_from_a_blocked_slot(self) -> None:
        # These two refusals call for opposite operator responses — raise the budget vs. go unwedge
        # a stuck run — so the single flat `refused` outcome could not drive either alert.
        cohort = self._backfillable_cohort()

        with (
            patch.object(COHORT_BACKFILL_TRIGGER_TASK_COUNTER, "labels") as counter,
            override_settings(**{**BACKFILL_TASK_SETTINGS, "BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET": 1}),
            patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes") as estimate,
        ):
            estimate.return_value = PersonSeedEstimate(
                estimated_persons=10,
                pinned_condition_count=1,
                bytes_per_seed=294,
                estimated_topic_bytes=2_940,
                budget_bytes=1,
            )
            trigger_cohort_backfill_run_task(
                self.team.pk, cohort.pk, "cohort_created", CohortBackfillKind.PERSON_PROPERTY.value
            )

        counter.assert_called_once_with(
            backfill_kind=CohortBackfillKind.PERSON_PROPERTY.value, outcome="refused_over_budget"
        )

        with override_settings(**BACKFILL_TASK_SETTINGS):
            trigger_cohort_backfill_run_task(
                self.team.pk, cohort.pk, "cohort_created", CohortBackfillKind.BEHAVIORAL.value
            )
            with patch.object(COHORT_BACKFILL_TRIGGER_TASK_COUNTER, "labels") as counter:
                trigger_cohort_backfill_run_task(
                    self.team.pk, cohort.pk, "cohort_edited", CohortBackfillKind.BEHAVIORAL.value
                )

        counter.assert_called_once_with(
            backfill_kind=CohortBackfillKind.BEHAVIORAL.value, outcome="refused_slot_occupied"
        )

    def test_every_backfill_refusal_reason_has_a_trigger_outcome(self) -> None:
        # A reason with no mapping entry falls back to the flat `refused`, which reads as an
        # unclassified refusal rather than an omission. Catch the drift here instead.
        self.assertEqual(set(COHORT_BACKFILL_REFUSAL_OUTCOMES), set(BackfillRefusalReason))
        # The alert rules match these literals, so a rename has to break a test, not a dashboard.
        self.assertEqual(
            set(COHORT_BACKFILL_REFUSAL_OUTCOMES.values()),
            {"refused_over_budget", "refused_slot_occupied", "refused_ineligible", "refused_transient"},
        )

    def test_trigger_backfill_run_task_rechecks_the_allowlist_at_execution_time(self) -> None:
        # Tasks sit in the queue for the debounce countdown, so an operator shrinking the allowlist
        # during an incident has to stop those too, not only new enqueues.
        cohort = self._backfillable_cohort()

        with override_settings(
            REALTIME_COHORT_TEAM_ALLOWLIST="all",
            BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=True,
            BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=True,
        ):
            trigger_cohort_backfill_run_task(
                self.team.pk, cohort.pk, "cohort_edited", CohortBackfillKind.BEHAVIORAL.value
            )

        self.assertFalse(CohortBackfillRun.objects.for_team(self.team.pk).exists())

    def test_safe_save_cohort_state_handles_errors(self) -> None:
        cohort = Cohort.objects.create(
            team_id=self.team.pk,
            name="test_cohort",
            is_static=True,
            count=0,
        )

        with patch.object(cohort, "save", side_effect=Exception("Database error")) as mock_save:
            cohort._safe_save_cohort_state(team_id=self.team.pk, processing_error=None)

        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertEqual(mock_save.call_count, 2)

    @parameterized.expand(
        [
            ("success", None, ["is_calculating", "last_calculation", "errors_calculating", "count"]),
            (
                "error",
                Exception("processing failed"),
                ["is_calculating", "errors_calculating", "last_error_at", "count"],
            ),
        ]
    )
    def test_safe_save_cohort_state_passes_update_fields(
        self, _name: str, processing_error: Exception | None, expected_update_fields: list[str]
    ) -> None:
        cohort = Cohort.objects.create(
            team_id=self.team.pk,
            name="test_cohort",
            is_static=True,
            count=0,
        )

        with patch.object(cohort, "save") as mock_save:
            cohort._safe_save_cohort_state(team_id=self.team.pk, processing_error=processing_error)

        mock_save.assert_called_once_with(update_fields=expected_update_fields)

    def test_safe_save_cohort_state_does_not_trigger_downstream_signals(self) -> None:
        cohort = Cohort.objects.create(
            team_id=self.team.pk,
            name="test_cohort",
            is_static=True,
            count=0,
        )

        with (
            patch("products.cohorts.backend.models.dependencies._on_cohort_changed") as mock_dep_cache,
            patch("products.feature_flags.backend.tasks.update_team_flags_cache") as mock_flags_cache,
            patch("products.cdp.backend.tasks.hog_functions.refresh_affected_hog_functions") as mock_hog_refresh,
        ):
            cohort._safe_save_cohort_state(team_id=self.team.pk, processing_error=None)

        mock_dep_cache.assert_not_called()
        mock_flags_cache.delay.assert_not_called()
        mock_hog_refresh.delay.assert_not_called()

    def _run_calculate_cohort_ch(
        self, cohort_id: int, pending_version: int = 1, *, retries: int = 0, called_directly: bool = False
    ) -> None:
        task = calculate_cohort_ch
        task.push_request(retries=retries, called_directly=called_directly, is_eager=True)
        try:
            task.run(cohort_id, pending_version)
        finally:
            task.pop_request()

    @parameterized.expand(
        [
            ("operational_error", OperationalError("connection reset")),
            ("interface_error", InterfaceError("connection already closed")),
        ]
    )
    def test_calculate_cohort_ch_schedules_a_retry_and_keeps_is_calculating(self, _name: str, error: Exception) -> None:
        # A connection-pooler blip on the task's first ORM read used to strand the cohort "in
        # flight" for an hour, until reset_stuck_cohorts caught it.
        # Celery raising Retry rather than the original error is what proves one was scheduled, and
        # is_calculating must not be cleared while the recalculation still has attempts left.
        cohort = Cohort.objects.create(team=self.team, name="test_cohort", is_calculating=True, pending_version=1)

        with (
            patch.object(Cohort.objects, "get", side_effect=error),
            self.assertRaises(Retry),
        ):
            self._run_calculate_cohort_ch(cohort.id)

        cohort.refresh_from_db()
        self.assertTrue(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 0)

    @parameterized.expand(
        [
            # pending_version 1 is the shape every real cohort reaches this task with:
            # _prepare_cohort_for_calculation stamps it in the same save that sets is_calculating.
            ("non_retryable_error", ValueError("boom"), 0, False, 1),
            ("retries_exhausted", OperationalError("connection reset"), COHORT_RECALCULATION_MAX_RETRIES, False, 1),
            ("called_directly", OperationalError("connection reset"), 0, True, 1),
            # Documented fallback: a cohort that never got a pending_version still has to clear.
            ("null_pending_version", ValueError("boom"), 0, False, None),
        ]
    )
    def test_calculate_cohort_ch_clears_is_calculating_when_recalculation_will_not_be_retried(
        self, _name: str, error: Exception, retries: int, called_directly: bool, pending_version: Optional[int]
    ) -> None:
        # Whether the error can never be retried, retries are exhausted, or the task was called
        # synchronously (the management command) so no retry machinery is behind it, the
        # recalculation is never going to run again - the cohort must not stay "in flight" until
        # the hourly reset_stuck_cohorts job. errors_calculating and last_error_at have to be
        # stamped with it, because they are the only brakes on re-enqueueing the cohort against a
        # database that is still failing.
        cohort = Cohort.objects.create(
            team=self.team, name="test_cohort", is_calculating=True, pending_version=pending_version
        )

        with patch.object(Cohort.objects, "get", side_effect=error):
            with self.assertRaises(type(error)):
                self._run_calculate_cohort_ch(cohort.id, retries=retries, called_directly=called_directly)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)
        self.assertIsNotNone(cohort.last_error_at)

    def test_calculate_cohort_ch_retries_when_a_deploy_cancels_the_recalculation_query(self) -> None:
        # The reason 394 got an importable class: a deploy cancelling the in-flight recalculation
        # query has to be retried rather than killing the task outright, and a pending retry has to
        # leave the cohort looking exactly like a running one. errors_calculating must stay at 0 -
        # charged per attempt instead of per failed run, a single bad deploy would push the cohort
        # most of the way to the MAX_ERRORS_CALCULATING cutoff that drops it from recalculation for
        # good. is_calculating must stay set, because with the counter deliberately unstamped it is
        # the only thing keeping the cohort out of the scheduler's candidate queryset during the
        # backoff - a superseding calculation would bump pending_version and no-op the retry.
        cohort = Cohort.objects.create(team=self.team, name="test_cohort", is_calculating=True, pending_version=1)

        with (
            patch(
                "products.cohorts.backend.models.util.recalculate_cohortpeople",
                side_effect=CHQueryErrorQueryWasCancelled(
                    "Query was cancelled.", code=394, code_name="query_was_cancelled"
                ),
            ),
            self.assertRaises(Retry),
        ):
            self._run_calculate_cohort_ch(cohort.id)

        cohort.refresh_from_db()
        self.assertTrue(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertIsNone(cohort.last_error_at)

    def test_calculate_cohort_ch_skips_an_obsolete_pending_version(self) -> None:
        # A newer save superseded this task's version. Without the guard both tasks would run a
        # full ClickHouse recalculation of the same cohort side by side.
        cohort = Cohort.objects.create(team=self.team, name="test_cohort", is_calculating=True)
        Cohort.objects.filter(pk=cohort.pk).update(pending_version=4)

        with patch.object(Cohort, "calculate_people_ch") as mock_calculate:
            self._run_calculate_cohort_ch(cohort.id, 2)

        mock_calculate.assert_not_called()

    def test_calculate_cohort_ch_leaves_is_calculating_for_a_newer_pending_version(self) -> None:
        # A newer save bumped pending_version and enqueued its own task. This older task failing
        # must not clear the flag out from under the calculation that superseded it.
        cohort = Cohort.objects.create(team=self.team, name="test_cohort", is_calculating=True)
        Cohort.objects.filter(pk=cohort.pk).update(pending_version=4)

        with patch.object(Cohort.objects, "get", side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                self._run_calculate_cohort_ch(cohort.id, 2)

        cohort.refresh_from_db()
        self.assertTrue(cohort.is_calculating)

    def test_insert_cohort_from_query_count_updated_on_exception(self) -> None:
        from posthog.tasks.calculate_cohort import insert_cohort_from_query

        cohort = Cohort.objects.create(
            team_id=self.team.pk,
            name="test_query_cohort",
            is_static=True,
            count=0,
            query={"kind": "HogQLQuery", "query": "SELECT person_id FROM persons LIMIT 10"},
        )

        with (
            patch("products.cohorts.backend.models.util.insert_cohort_query_actors_into_ch") as mock_insert_ch,
            patch("products.cohorts.backend.models.util.insert_cohort_people_into_pg") as mock_insert_pg,
        ):
            mock_insert_ch.side_effect = Exception("Simulated query processing error")
            mock_insert_pg.side_effect = Exception("Simulated pg insert error")

            insert_cohort_from_query(cohort.id, self.team.pk)

            cohort.refresh_from_db()
            self.assertEqual(
                cohort.count, 0, "Count should be updated using PostgreSQL even when query processing fails"
            )
            self.assertFalse(cohort.is_calculating, "Cohort should not be in calculating state")
            self.assertGreater(cohort.errors_calculating, 0, "Should have recorded the processing error")

    @parameterized.expand(
        [
            # (exception raised, expected capture_exception call count)
            ("system_error", Exception("Simulated query processing error"), 1),
            ("user_query_error", QueryError("Unable to resolve field: distinct_ids"), 0),
        ]
    )
    def test_insert_cohort_from_query_only_captures_system_errors(
        self, _name: str, raised: Exception, expected_capture_calls: int
    ) -> None:
        from posthog.tasks.calculate_cohort import insert_cohort_from_query

        cohort = Cohort.objects.create(
            team_id=self.team.pk,
            name="test_query_cohort",
            is_static=True,
            count=0,
            query={"kind": "HogQLQuery", "query": "SELECT distinct_ids FROM persons LIMIT 10"},
        )

        with (
            patch("products.cohorts.backend.models.util.insert_cohort_query_actors_into_ch") as mock_insert_ch,
            patch("posthog.tasks.calculate_cohort.capture_exception") as mock_capture,
        ):
            mock_insert_ch.side_effect = raised

            insert_cohort_from_query(cohort.id, self.team.pk)

            self.assertEqual(mock_capture.call_count, expected_capture_calls)
            cohort.refresh_from_db()
            self.assertFalse(cohort.is_calculating, "Cohort should not be in calculating state")
            self.assertGreater(cohort.errors_calculating, 0, "Failure should be recorded regardless of error type")

    def test_insert_cohort_from_filters_count_updated_on_exception(self) -> None:
        cohort = Cohort.objects.create(
            team_id=self.team.pk,
            name="test_filters_cohort",
            is_static=True,
            count=0,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [{"key": "email", "type": "person", "value": "match@example.com"}],
                        }
                    ],
                }
            },
        )

        with (
            patch("products.cohorts.backend.models.util.insert_cohort_filter_actors_into_ch") as mock_insert_ch,
            patch("products.cohorts.backend.models.util.insert_cohort_people_into_pg") as mock_insert_pg,
        ):
            mock_insert_ch.side_effect = Exception("Simulated filter processing error")
            mock_insert_pg.side_effect = Exception("Simulated pg insert error")

            insert_cohort_from_filters(cohort.id, self.team.pk)

            cohort.refresh_from_db()
            self.assertEqual(cohort.count, 0, "Count should remain available even when filter processing fails")
            self.assertFalse(cohort.is_calculating, "Cohort should not be in calculating state")
            self.assertGreater(cohort.errors_calculating, 0, "Should have recorded the processing error")

    @patch("posthog.tasks.calculate_cohort.chain")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
    def test_increment_version_and_enqueue_calculate_cohort_with_referencing_cohorts(
        self, mock_calculate_cohort_ch_si: MagicMock, mock_chain: MagicMock
    ) -> None:
        cohort_a = Cohort.objects.create(
            team=self.team,
            name="Cohort A",
            filters={
                "properties": {"type": "AND", "values": [{"key": "$browser", "value": "Chrome", "type": "person"}]}
            },
            is_static=False,
        )

        cohort_b = Cohort.objects.create(
            team=self.team,
            name="Cohort B (references A)",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "id", "value": cohort_a.id, "type": "cohort"},
                        {"key": "$os", "value": "Windows", "type": "person"},
                    ],
                }
            },
            is_static=False,
        )

        cohort_c = Cohort.objects.create(
            team=self.team,
            name="Cohort C (references B)",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "id", "value": cohort_b.id, "type": "cohort"},
                        {"key": "$country", "value": "US", "type": "person"},
                    ],
                }
            },
            is_static=False,
        )

        mock_chain_instance = MagicMock()
        mock_chain.return_value = mock_chain_instance
        mock_task = MagicMock()
        mock_calculate_cohort_ch_si.return_value = mock_task

        increment_version_and_enqueue_calculate_cohort(cohort_a, initiating_user=None)

        self.assertEqual(mock_calculate_cohort_ch_si.call_count, 3)

        actual_calls = mock_calculate_cohort_ch_si.call_args_list
        actual_cohort_ids = {call[0][0] for call in actual_calls}
        expected_cohort_ids = {cohort_a.id, cohort_b.id, cohort_c.id}
        self.assertEqual(actual_cohort_ids, expected_cohort_ids)

        mock_chain.assert_called_once()
        mock_chain_instance.apply_async.assert_called_once()

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_increment_version_and_enqueue_resets_is_calculating_when_delay_fails(
        self, mock_calculate_cohort_ch_delay: MagicMock
    ) -> None:
        # A broker outage shouldn't strand the cohort looking "in flight": nothing was actually
        # enqueued, so is_calculating must go back to False rather than wait an hour for the
        # stuck-cohort reset to notice.
        cohort = Cohort.objects.create(team=self.team, name="Standalone Cohort", is_static=False)
        mock_calculate_cohort_ch_delay.side_effect = Exception("broker unavailable")

        with self.assertRaises(Exception):
            increment_version_and_enqueue_calculate_cohort(cohort, initiating_user=None)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.pending_version, 1)

    @patch("posthog.tasks.calculate_cohort.chain")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
    def test_increment_version_and_enqueue_resets_is_calculating_for_chain_when_apply_async_fails(
        self, mock_calculate_cohort_ch_si: MagicMock, mock_chain: MagicMock
    ) -> None:
        # Same as above, but for the dependency-chain path: a mid-chain broker failure must not
        # strand any cohort in the chain, not just the one the caller passed in.
        cohort_a = Cohort.objects.create(team=self.team, name="Cohort A", is_static=False)
        cohort_b = Cohort.objects.create(
            team=self.team,
            name="Cohort B (references A)",
            filters={"properties": {"type": "AND", "values": [{"key": "id", "value": cohort_a.id, "type": "cohort"}]}},
            is_static=False,
        )

        mock_chain.return_value.apply_async.side_effect = Exception("broker unavailable")
        mock_calculate_cohort_ch_si.return_value = MagicMock()

        with self.assertRaises(Exception):
            increment_version_and_enqueue_calculate_cohort(cohort_b, initiating_user=None)

        cohort_a.refresh_from_db()
        cohort_b.refresh_from_db()
        self.assertFalse(cohort_a.is_calculating)
        self.assertFalse(cohort_b.is_calculating)


class TestCalculateCohortFromListRetries(APIBaseTest):
    def _create_static_cohort(self) -> Cohort:
        # Mirrors the enqueue site, which flips is_calculating before dispatching the task.
        return Cohort.objects.create(
            team_id=self.team.pk,
            name="csv_upload_cohort",
            is_static=True,
            is_calculating=True,
        )

    def _run_task(self, cohort: Cohort, *, retries: int, called_directly: bool) -> None:
        task = calculate_cohort_from_list
        task.push_request(retries=retries, called_directly=called_directly, is_eager=True)
        try:
            task.run(cohort.id, ["user123"], team_id=self.team.id, id_type="distinct_id")
        finally:
            task.pop_request()

    def test_failed_import_keeps_previous_resolution_counts(self) -> None:
        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
            last_import_total_count=10,
            last_import_unmatched_count=2,
        )
        task = calculate_cohort_from_list
        task.push_request(retries=0, called_directly=True, is_eager=True)
        try:
            with (
                patch.object(Cohort, "insert_users_by_email", side_effect=RuntimeError("lookup failed")),
                self.assertRaisesRegex(RuntimeError, "lookup failed"),
            ):
                task.run(
                    cohort.id,
                    ["one@example.com", "two@example.com"],
                    team_id=self.team.id,
                    id_type="email",
                )
        finally:
            task.pop_request()

        cohort.refresh_from_db()
        self.assertEqual(cohort.last_import_total_count, 10)
        self.assertEqual(cohort.last_import_unmatched_count, 2)

    @parameterized.expand(
        [
            ("retries_exhausted", ClickHouseAtCapacity, calculate_cohort_from_list.max_retries, False),
            ("called_directly", ClickHouseAtCapacity, 0, True),
            ("not_retryable", ValueError, 0, False),
        ]
    )
    @patch("products.cohorts.backend.models.util.insert_static_cohort")
    def test_records_failure_when_nothing_will_retry(
        self,
        _name: str,
        error_class: type[Exception],
        retries: int,
        called_directly: bool,
        mock_insert_ch: MagicMock,
    ) -> None:
        # raise_on_error hands terminal-state finalization to the task, so whenever no retry
        # follows, the task itself has to clear is_calculating and bump errors_calculating.
        # Otherwise the cohort is stranded looking in-flight forever with no recorded error.
        mock_insert_ch.side_effect = error_class("boom")
        create_person(team=self.team, distinct_ids=["user123"])
        cohort = self._create_static_cohort()

        with self.assertRaises(error_class):
            self._run_task(cohort, retries=retries, called_directly=called_directly)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)
        self.assertIsNotNone(cohort.last_error_at)

    @patch("products.cohorts.backend.models.util.insert_static_cohort")
    def test_leaves_state_untouched_while_retries_remain(self, mock_insert_ch: MagicMock) -> None:
        # A transient failure with attempts left belongs to the pending autoretry, so recording it
        # now would show a cohort that is still being retried as errored and no longer calculating.
        # Celery raising Retry rather than the original error is what confirms one was scheduled.
        mock_insert_ch.side_effect = ClickHouseAtCapacity()
        create_person(team=self.team, distinct_ids=["user123"])
        cohort = self._create_static_cohort()

        with self.assertRaises(Retry):
            self._run_task(cohort, retries=0, called_directly=False)

        cohort.refresh_from_db()
        self.assertTrue(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 0)

    @patch("products.cohorts.backend.models.util.insert_static_cohort")
    def test_retry_after_transient_failure_completes_the_cohort(self, mock_insert_ch: MagicMock) -> None:
        # What the retry buys: the attempt that follows a capacity blip populates every member and
        # finalizes clean state, and re-running the whole list adds no duplicate members.
        mock_insert_ch.side_effect = [ClickHouseAtCapacity(), None]
        create_person(team=self.team, distinct_ids=["user123"])
        cohort = self._create_static_cohort()

        with self.assertRaises(Retry):
            self._run_task(cohort, retries=0, called_directly=False)

        self._run_task(cohort, retries=1, called_directly=False)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertEqual(count_cohort_members(cohort.team_id, cohort.pk), 1)
