from collections.abc import Callable
from contextlib import nullcontext, suppress
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import APIBaseTest, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import DEFAULT_DB_ALIAS, InterfaceError, OperationalError
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

import grpc
from celery import Task
from celery.exceptions import Reject, Retry, SoftTimeLimitExceeded
from dateutil.relativedelta import relativedelta
from parameterized import parameterized

from posthog.hogql.errors import QueryError

from posthog.clickhouse.client import sync_execute
from posthog.errors import CHQueryErrorQueryWasCancelled, InternalCHQueryError
from posthog.exceptions import ClickHouseAtCapacity
from posthog.models.person.sql import REPLACE_ROW_OFFSET
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
    STATIC_POPULATION_MAX_RETRIES,
    _end_pending_population,
    calculate_cohort_ch,
    calculate_cohort_from_list,
    collect_cohort_query_stats,
    enqueue_cohorts_to_calculate,
    increment_version_and_enqueue_calculate_cohort,
    insert_cohort_from_filters,
    insert_cohort_from_query,
    refresh_static_cohort_count,
    reset_stuck_cohorts,
    schedule_static_cohort_count_refresh,
    trigger_cohort_backfill_run_task,
    update_cohort_metrics,
)
from posthog.test.persons import create_person

from products.cohorts.backend.backfill.runs import BackfillRefusalReason
from products.cohorts.backend.backfill.sizing import PersonSeedEstimate
from products.cohorts.backend.models.backfill import CohortBackfillKind, CohortBackfillRun
from products.cohorts.backend.models.calculation_history import CohortCalculationHistory
from products.cohorts.backend.models.cohort import Cohort, CohortPopulationMode, CohortType
from products.cohorts.backend.models.util import (
    REPLACE_FLOOR_CLOCK_MARGIN,
    CohortErrorCode,
    PopulationEmptyResult,
    PopulationMarkerClockSkew,
    StaticCohortReadBackIncomplete,
    count_cohort_members,
    delete_cohort_members_by_person_ids,
    get_friendly_error_message,
    insert_cohort_query_actors_into_ch,
    insert_static_cohort,
    list_cohort_member_ids,
    prune_stale_static_cohort_rows,
)

# The catalog drops a leaf with no bytecode, and `_calculate_realtime_support` grants
# `cohort_type=REALTIME` only when every leaf compiled to bytecode. A fixture without it is a
# cohort shape no realtime cohort can have.
_BYTECODE = ["_H", 1, 32, "matched", 32, "event", 1, 1, 11]


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
    "BEHAVIORAL_BACKFILL_MAX_SCAN_EVENTS_PER_DAY": 0,
}


def _rpc_error(code: grpc.StatusCode) -> grpc.RpcError:
    error = grpc.RpcError()
    error.code = MagicMock(return_value=code)
    return error


PERSONS_HOGQL_QUERY = {"kind": "HogQLQuery", "query": "SELECT id FROM persons"}
QUERY_CH_INSERT_PATH = "products.cohorts.backend.models.util.insert_cohort_query_actors_into_ch"
FILTERS_CH_INSERT_PATH = "products.cohorts.backend.models.util.insert_cohort_filter_actors_into_ch"
PG_SYNC_PATH = "products.cohorts.backend.models.util.insert_cohort_people_into_pg"
COHORT_READ_PATH = "posthog.tasks.calculate_cohort.Cohort.objects.get"


def _claim_replace(cohort: Cohort, claimed_at: datetime | None = None) -> None:
    Cohort.objects.filter(pk=cohort.pk).update(
        is_calculating=True,
        pending_population_mode=CohortPopulationMode.REPLACE,
        population_claimed_at=claimed_at if claimed_at is not None else timezone.now().replace(microsecond=0),
    )


def _static_cohort_rows(team_id: int, cohort_id: int) -> list[tuple[str, int]]:
    rows = sync_execute(
        "SELECT person_id, _offset FROM person_static_cohort WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s",
        {"team_id": team_id, "cohort_id": cohort_id},
    )
    return [(str(person_id), offset) for person_id, offset in rows]


PERSON_EMAIL_FILTERS = {
    "properties": {
        "type": "AND",
        "values": [
            {
                "type": "AND",
                "values": [{"key": "email", "type": "person", "value": "match@example.com"}],
            }
        ],
    }
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
            with time_machine.travel("2021-01-01 00:06:34", tick=False):
                event_factory(
                    team=self.team,
                    event="$pageview",
                    distinct_id="blabla",
                    properties={"$math_prop": 1},
                    timestamp="2021-01-01T12:00:00Z",
                )

            with time_machine.travel("2021-01-02 00:06:34", tick=False):
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
    def setUp(self) -> None:
        super().setUp()
        flag_patcher = patch("posthog.tasks.calculate_cohort.is_static_cohort_replace_enabled", return_value=True)
        self.addCleanup(flag_patcher.stop)
        self.mock_replace_flag = flag_patcher.start()

    def _backfillable_cohort(self) -> Cohort:
        return Cohort.objects.create(
            team=self.team,
            name="backfill trigger",
            cohort_type=CohortType.REALTIME,
            realtime_enabled_at=timezone.now(),
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
                            "bytecode": _BYTECODE,
                        },
                        {
                            "type": "person",
                            "key": "email",
                            "value": ["person@example.com"],
                            "operator": "exact",
                            "conditionHash": "person0000000001",
                            "bytecode": _BYTECODE,
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
            ("empty_replace", PopulationEmptyResult("the replace query matched nobody"), 0),
        ]
    )
    def test_insert_cohort_from_query_only_captures_system_errors(
        self, _name: str, raised: Exception, expected_capture_calls: int
    ) -> None:
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

    @parameterized.expand(
        [
            ("query", insert_cohort_from_query, QUERY_CH_INSERT_PATH),
            ("filters", insert_cohort_from_filters, FILTERS_CH_INSERT_PATH),
        ]
    )
    @override_settings(DEBUG=False)
    @patch("products.cohorts.backend.models.util.insert_cohort_members")
    def test_static_population_records_personhog_sync_failure(
        self, _name: str, task: Task, ch_insert_path: str, mock_insert_members: MagicMock
    ) -> None:
        person = create_person(team=self.team, distinct_ids=["personhog-sync-failure"])
        cohort = Cohort.objects.create(
            team=self.team,
            name="static cohort",
            is_static=True,
            query=PERSONS_HOGQL_QUERY,
        )
        insert_static_cohort([person.uuid], cohort.pk, team_id=self.team.pk)
        mock_insert_members.side_effect = ValueError("personhog unavailable")

        with patch(ch_insert_path):
            task(cohort.id, self.team.pk)

        cohort.refresh_from_db()
        self.assertEqual(cohort.errors_calculating, 1)
        self.assertFalse(cohort.is_calculating)
        self.assertIsNone(cohort.last_calculation)

        # The history row is what the cohort API reads `last_error_message` from, so without it the
        # failed population reads as a cohort that matched nobody.
        history = CohortCalculationHistory.objects.get(cohort=cohort)
        self.assertEqual(history.error_code, CohortErrorCode.UNKNOWN)
        self.assertIsNotNone(history.finished_at)
        # The history tab renders `error` verbatim to anyone with cohort read access, so the raw
        # exception text stays out of it.
        self.assertEqual(history.error, get_friendly_error_message(CohortErrorCode.UNKNOWN, will_retry=False))
        assert history.error is not None
        self.assertNotIn("personhog unavailable", history.error)

    @parameterized.expand(
        [
            (
                "query_personhog_unavailable",
                insert_cohort_from_query,
                QUERY_CH_INSERT_PATH,
                PG_SYNC_PATH,
                lambda: _rpc_error(grpc.StatusCode.UNAVAILABLE),
            ),
            (
                "filters_personhog_unavailable",
                insert_cohort_from_filters,
                FILTERS_CH_INSERT_PATH,
                PG_SYNC_PATH,
                lambda: _rpc_error(grpc.StatusCode.UNAVAILABLE),
            ),
            (
                "query_personhog_shedding_load",
                insert_cohort_from_query,
                QUERY_CH_INSERT_PATH,
                PG_SYNC_PATH,
                lambda: _rpc_error(grpc.StatusCode.RESOURCE_EXHAUSTED),
            ),
            (
                "query_personhog_query_error",
                insert_cohort_from_query,
                QUERY_CH_INSERT_PATH,
                PG_SYNC_PATH,
                lambda: _rpc_error(grpc.StatusCode.INTERNAL),
            ),
            (
                "query_postgres_connection_dropped",
                insert_cohort_from_query,
                QUERY_CH_INSERT_PATH,
                PG_SYNC_PATH,
                lambda: OperationalError("server closed the connection unexpectedly"),
            ),
            (
                "query_postgres_dropped_on_first_read",
                insert_cohort_from_query,
                QUERY_CH_INSERT_PATH,
                COHORT_READ_PATH,
                lambda: OperationalError("server closed the connection unexpectedly"),
            ),
            (
                "query_ran_past_the_soft_time_limit",
                insert_cohort_from_query,
                QUERY_CH_INSERT_PATH,
                PG_SYNC_PATH,
                lambda: SoftTimeLimitExceeded(),
            ),
            (
                "query_read_back_incomplete",
                insert_cohort_from_query,
                QUERY_CH_INSERT_PATH,
                PG_SYNC_PATH,
                lambda: StaticCohortReadBackIncomplete("Read 0 of 1 rows"),
            ),
            (
                "query_marker_clock_skew",
                insert_cohort_from_query,
                QUERY_CH_INSERT_PATH,
                PG_SYNC_PATH,
                lambda: PopulationMarkerClockSkew("rows stamped 30s ahead of this host's clock"),
            ),
            (
                "query_too_few_live_replicas",
                insert_cohort_from_query,
                QUERY_CH_INSERT_PATH,
                PG_SYNC_PATH,
                lambda: InternalCHQueryError("too few live replicas", code=285),
            ),
            (
                "query_quorum_locked",
                insert_cohort_from_query,
                QUERY_CH_INSERT_PATH,
                PG_SYNC_PATH,
                lambda: InternalCHQueryError("quorum for previous write", code=286),
            ),
            (
                "query_replica_not_in_quorum",
                insert_cohort_from_query,
                QUERY_CH_INSERT_PATH,
                PG_SYNC_PATH,
                lambda: InternalCHQueryError("replica is not in quorum", code=289),
            ),
            (
                "query_insert_status_unknown",
                insert_cohort_from_query,
                QUERY_CH_INSERT_PATH,
                PG_SYNC_PATH,
                lambda: InternalCHQueryError("unknown status of insert", code=319),
            ),
        ]
    )
    def test_static_population_retries_a_transient_failure(
        self,
        _name: str,
        task: Task,
        ch_insert_path: str,
        failing_path: str,
        error_factory: Callable[[], Exception],
    ) -> None:
        # The enqueue site flips is_calculating before it dispatches, so a retry pending on the first
        # read must leave that flag alone rather than clear it.
        cohort = Cohort.objects.create(team=self.team, name="static cohort", is_static=True, is_calculating=True)
        task.push_request(retries=0, called_directly=False, is_eager=True)
        try:
            with (
                patch(ch_insert_path),
                patch(failing_path, side_effect=error_factory()),
                self.assertRaises(Retry),
            ):
                task.run(cohort.id, self.team.pk)
        finally:
            task.pop_request()

        cohort.refresh_from_db()
        self.assertTrue(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertIsNone(cohort.last_calculation)
        self.assertIsNotNone(cohort.last_error_at)

    @parameterized.expand(
        [
            ("retry_scheduled", 0, True),
            ("retries_exhausted", STATIC_POPULATION_MAX_RETRIES, False),
        ]
    )
    @override_settings(DEBUG=False)
    def test_static_population_history_records_whether_another_attempt_is_coming(
        self, _name: str, retries: int, another_attempt_coming: bool
    ) -> None:
        cohort = Cohort.objects.create(team=self.team, name="static cohort", is_static=True, is_calculating=True)
        insert_cohort_from_query.push_request(retries=retries, called_directly=False, is_eager=True)
        try:
            with patch(QUERY_CH_INSERT_PATH), patch(PG_SYNC_PATH, side_effect=ClickHouseAtCapacity()):
                if another_attempt_coming:
                    with self.assertRaises(Retry):
                        insert_cohort_from_query.run(cohort.id, self.team.pk)
                else:
                    insert_cohort_from_query.run(cohort.id, self.team.pk)
        finally:
            insert_cohort_from_query.pop_request()

        # One row records one attempt, so a queued retry must not leave this one open and reading
        # as a population still in flight.
        history = CohortCalculationHistory.objects.get(cohort=cohort)
        self.assertIsNotNone(history.finished_at)
        self.assertEqual(history.error_code, CohortErrorCode.CAPACITY)
        assert history.error is not None
        # The history tab renders this text per attempt, so an attempt that already queued another
        # one must not read as terminal.
        self.assertEqual("automatically retry" in history.error, another_attempt_coming)

    @parameterized.expand(
        [
            ("replace", CohortPopulationMode.REPLACE),
            ("append", CohortPopulationMode.APPEND),
        ]
    )
    def test_query_population_records_claimed_mode_in_history(self, _name: str, mode: CohortPopulationMode) -> None:
        cohort = Cohort.objects.create(
            team=self.team,
            name="static",
            is_static=True,
            is_calculating=True,
            pending_population_mode=mode,
            population_claimed_at=timezone.now().replace(microsecond=0),
        )
        with (
            patch(QUERY_CH_INSERT_PATH, side_effect=ClickHouseAtCapacity()),
            patch(PG_SYNC_PATH),
        ):
            insert_cohort_from_query(cohort.id, self.team.pk)

        history = CohortCalculationHistory.objects.get(cohort=cohort)
        self.assertEqual(history.mode, mode)

    def test_a_failed_import_records_its_own_reason_rather_than_an_older_one(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="static cohort", is_static=True)
        person = create_person(team=self.team, distinct_ids=["import-failure"])
        # An earlier query population failed and left the newest errored row. `last_error_message`
        # takes that row over the cohort's whole life, so an import that records nothing of its own
        # reports this stale reason in place of the one that just happened.
        CohortCalculationHistory.objects.create(
            team=self.team,
            cohort=cohort,
            filters={},
            started_at=timezone.now() - relativedelta(hours=1),
            finished_at=timezone.now() - relativedelta(hours=1),
            error=get_friendly_error_message(CohortErrorCode.DATA_LIMIT, will_retry=False),
            error_code=CohortErrorCode.DATA_LIMIT,
        )

        with (
            patch(
                "products.cohorts.backend.models.util.insert_cohort_members",
                side_effect=ValueError("personhog unavailable"),
            ),
            self.assertRaises(ValueError),
        ):
            calculate_cohort_from_list(cohort.id, [str(person.uuid)], team_id=self.team.pk, id_type="person_id")

        newest_failure = (
            CohortCalculationHistory.objects.filter(cohort=cohort)
            .exclude(error__isnull=True)
            .order_by("-started_at")
            .first()
        )
        assert newest_failure is not None
        self.assertEqual(newest_failure.error_code, CohortErrorCode.UNKNOWN)
        self.assertIsNotNone(newest_failure.finished_at)

    @parameterized.expand(
        [
            ("query", insert_cohort_from_query, QUERY_CH_INSERT_PATH),
            ("filters", insert_cohort_from_filters, FILTERS_CH_INSERT_PATH),
        ]
    )
    def test_static_population_records_a_transient_failure_once_retries_run_out(
        self, _name: str, task: Task, ch_insert_path: str
    ) -> None:
        cohort = Cohort.objects.create(team=self.team, name="static cohort", is_static=True, is_calculating=True)
        task.push_request(retries=STATIC_POPULATION_MAX_RETRIES, called_directly=False, is_eager=True)
        try:
            with (
                patch(ch_insert_path),
                patch(PG_SYNC_PATH, side_effect=_rpc_error(grpc.StatusCode.UNAVAILABLE)),
            ):
                task.run(cohort.id, self.team.pk)
        finally:
            task.pop_request()

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)
        self.assertIsNone(cohort.last_calculation)
        self.assertIsNotNone(cohort.last_error_at)

    @parameterized.expand(
        [
            ("query", insert_cohort_from_query, QUERY_CH_INSERT_PATH),
            ("filters", insert_cohort_from_filters, FILTERS_CH_INSERT_PATH),
        ]
    )
    def test_static_population_retry_skips_a_finished_clickhouse_insert(
        self, _name: str, task: Task, ch_insert_path: str
    ) -> None:
        # Re-evaluating the source query costs the same hours again and inserts nothing, so an
        # attempt that only failed on the Postgres sync has to resume at that sync.
        cohort = Cohort.objects.create(team=self.team, name="static cohort", is_static=True)
        task.push_request(retries=0, called_directly=False, is_eager=True)
        try:
            with time_machine.travel(datetime(2026, 3, 1, 12, 0, 0), tick=False) as traveller:

                def slow_insert(*_args: object, **_kwargs: object) -> int:
                    traveller.shift(timedelta(hours=1))
                    return 7

                with (
                    patch(ch_insert_path, side_effect=slow_insert),
                    patch(PG_SYNC_PATH, side_effect=_rpc_error(grpc.StatusCode.UNAVAILABLE)),
                    self.assertRaises(Retry) as scheduled,
                ):
                    task.run(cohort.id, self.team.pk)

            with patch(ch_insert_path) as mock_insert_ch, patch(PG_SYNC_PATH) as mock_sync:
                task.run(cohort.id, self.team.pk, **scheduled.exception.sig.kwargs)
        finally:
            task.pop_request()

        mock_insert_ch.assert_not_called()
        # The retry still has to wait for the rows the first attempt wrote, or a lagging replica reads as empty.
        self.assertEqual(mock_sync.call_args.kwargs["min_rows"], 7)
        self.assertEqual(scheduled.exception.sig.kwargs["written_since"], "2026-03-01 12:00:00")
        self.assertEqual(mock_sync.call_args.kwargs["written_since"], "2026-03-01 12:00:00")

    @parameterized.expand(
        [
            # name, pending mode, Postgres sync error, retries already used, mode left, marker left
            ("replace_success_clears", CohortPopulationMode.REPLACE, None, 0, None, False),
            ("replace_retry_keeps", CohortPopulationMode.REPLACE, grpc.StatusCode.UNAVAILABLE, 0, "replace", True),
            (
                "replace_exhausted_clears",
                CohortPopulationMode.REPLACE,
                grpc.StatusCode.UNAVAILABLE,
                STATIC_POPULATION_MAX_RETRIES,
                None,
                False,
            ),
            # The create path never claims, so a NULL mode has to run as an append.
            ("null_mode_appends", None, None, 0, None, False),
            # Every query PATCH claims an append, so this is the exit nearly every population takes.
            ("append_success_clears", CohortPopulationMode.APPEND, None, 0, None, False),
        ]
    )
    def test_query_population_run_fields_on_each_exit(
        self,
        _name: str,
        mode: CohortPopulationMode | None,
        sync_error: grpc.StatusCode | None,
        retries: int,
        mode_left: str | None,
        marker_left: bool,
    ) -> None:
        cohort = Cohort.objects.create(
            team=self.team,
            name="static cohort",
            is_static=True,
            query=PERSONS_HOGQL_QUERY,
            is_calculating=True,
            pending_population_mode=mode,
            population_claimed_at=timezone.now().replace(microsecond=0)
            if mode == CohortPopulationMode.REPLACE
            else None,
        )
        insert_cohort_from_query.push_request(retries=retries, called_directly=False, is_eager=True)
        try:
            with (
                # One match: a replace that matches nobody is refused before the sync.
                patch(QUERY_CH_INSERT_PATH, return_value=1) as mock_insert_ch,
                patch(PG_SYNC_PATH, return_value=1, side_effect=_rpc_error(sync_error) if sync_error else None),
                suppress(Retry),
            ):
                insert_cohort_from_query.run(cohort.id, self.team.pk)
        finally:
            insert_cohort_from_query.pop_request()

        cohort.refresh_from_db()
        self.assertEqual(
            (
                cohort.pending_population_mode,
                cohort.population_marker is not None,
                mock_insert_ch.call_args.kwargs.get("replace_marker") is not None,
            ),
            (mode_left, marker_left, mode == CohortPopulationMode.REPLACE),
        )
        self.assertEqual(cohort.is_calculating, sync_error is not None and retries == 0)

    @parameterized.expand(
        [
            # A sweep redispatch minted a newer marker mid-run, so this replace is fenced out.
            ("replace_superseded_mid_run", CohortPopulationMode.REPLACE, False),
            # A redispatched replace took the cohort over just before this append finalized.
            ("append_overtaken_before_finalize", CohortPopulationMode.APPEND, False),
            # The sweep reset took the cohort mid-run: it cleared the marker and released is_calculating,
            # but preserved the mode for the redispatch. The old worker must finalize nothing and leave the mode.
            ("sweep_reset_mid_run", CohortPopulationMode.REPLACE, True),
        ]
    )
    def test_query_population_overtaken_mid_run_finalizes_nothing(
        self, _name: str, mode: CohortPopulationMode, sweep_resets: bool
    ) -> None:
        cohort = Cohort.objects.create(
            team=self.team,
            name="static cohort",
            is_static=True,
            query=PERSONS_HOGQL_QUERY,
            is_calculating=True,
            pending_population_mode=mode,
            population_claimed_at=timezone.now().replace(microsecond=0)
            if mode == CohortPopulationMode.REPLACE
            else None,
        )
        newer_marker = timezone.now().replace(microsecond=0) + timedelta(minutes=5)

        def attempt_takes_over(*args: Any, **kwargs: Any) -> int:
            if sweep_resets:
                # Past the soft time limit, so the sweep no longer counts this attempt's open history row as live.
                with (
                    time_machine.travel(timezone.now() + relativedelta(hours=5), tick=False),
                    patch("posthog.tasks.calculate_cohort.insert_cohort_from_query.delay") as mock_delay,
                ):
                    reset_stuck_cohorts()
                    mock_delay.assert_called_once_with(cohort.pk, self.team.pk)
            else:
                Cohort.objects.filter(pk=cohort.pk).update(
                    pending_population_mode=CohortPopulationMode.REPLACE, population_marker=newer_marker
                )
            return 1

        with patch(QUERY_CH_INSERT_PATH, return_value=1), patch(PG_SYNC_PATH, side_effect=attempt_takes_over):
            insert_cohort_from_query(cohort.id, self.team.pk)

        cohort.refresh_from_db()
        expected = (
            (False, CohortPopulationMode.REPLACE, None)
            if sweep_resets
            else (True, CohortPopulationMode.REPLACE, newer_marker)
        )
        # The overtaking attempt or sweep still holds the cohort: nothing was released or cleared under it.
        self.assertEqual(
            (cohort.is_calculating, cohort.pending_population_mode, cohort.population_marker),
            expected,
        )
        # Losing ownership at finalize discards the attempt's history row so neither a spurious success, an
        # error banner, nor an open in-flight row remains.
        self.assertFalse(CohortCalculationHistory.objects.filter(cohort=cohort).exists())

    def test_query_replace_history_records_post_replace_count(self) -> None:
        tag = uuid4().hex
        p1 = create_person(team=self.team, distinct_ids=[f"{tag}-1"], properties={"tag": f"{tag}-keep"}, uuid=uuid4())
        p2 = create_person(team=self.team, distinct_ids=[f"{tag}-2"], properties={"tag": f"{tag}-keep"}, uuid=uuid4())
        p3 = create_person(team=self.team, distinct_ids=[f"{tag}-3"], properties={"tag": f"{tag}-drop"}, uuid=uuid4())
        flush_persons_and_events()

        cohort = Cohort.objects.create(
            team=self.team,
            name="static cohort",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{tag}-keep'"},
        )
        cohort.insert_users_list_by_uuid([str(p1.uuid), str(p2.uuid), str(p3.uuid)], team_id=self.team.pk)
        cohort.refresh_from_db()
        self.assertEqual(cohort.count, 3)

        claimed_at = timezone.now().replace(microsecond=0) + timedelta(seconds=10)
        _claim_replace(cohort, claimed_at=claimed_at)
        with time_machine.travel(claimed_at + timedelta(seconds=10), tick=False):
            insert_cohort_from_query(cohort.id, self.team.pk)

        cohort.refresh_from_db()
        history = CohortCalculationHistory.objects.filter(cohort=cohort).latest("started_at")
        self.assertEqual(cohort.count, 2)
        self.assertEqual(history.count, 2)
        self.assertEqual(set(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk)), {p1.id, p2.id})

    def test_query_population_keeps_history_when_finalize_ownership_check_hits_db_error(self) -> None:
        cohort = Cohort.objects.create(
            team=self.team,
            name="static cohort",
            is_static=True,
            query=PERSONS_HOGQL_QUERY,
            is_calculating=True,
        )

        with (
            patch(QUERY_CH_INSERT_PATH, return_value=1),
            patch(PG_SYNC_PATH),
            patch(
                "products.cohorts.backend.models.util.clear_population_run_fields",
                side_effect=[OperationalError("db gone"), OperationalError("db still gone")],
            ) as mock_clear,
            patch("products.cohorts.backend.models.util.capture_exception") as mock_capture,
            patch("products.cohorts.backend.models.util.connections") as mock_connections,
        ):
            insert_cohort_from_query(cohort.id, self.team.pk)

        self.assertEqual(mock_clear.call_count, 2)
        mock_connections[DEFAULT_DB_ALIAS].close.assert_called_once()
        mock_capture.assert_called_once()
        history = CohortCalculationHistory.objects.get(cohort=cohort)
        self.assertIsNotNone(history.finished_at)

    @parameterized.expand(
        [
            ("resumes_at_its_marker", None),
            # A sweep redispatch minted a newer marker while this retry waited in its backoff.
            ("newer_marker_minted", lambda marker: {"population_marker": marker + timedelta(seconds=30)}),
            # The sweep gave up on the run: it released the cohort and ended the replace.
            (
                "sweep_ended_the_run",
                lambda _marker: {"is_calculating": False, "pending_population_mode": None, "population_marker": None},
            ),
            # A user's append claimed the cohort after the sweep released it. Its token (no marker, mode append) is
            # one the retry would also hold if it ran as an append.
            (
                "user_claimed_an_append",
                lambda _marker: {"pending_population_mode": CohortPopulationMode.APPEND, "population_marker": None},
            ),
        ]
    )
    def test_query_replace_retry_after_the_clickhouse_insert(
        self, _name: str, takeover: Callable[[datetime], dict[str, Any]] | None
    ) -> None:
        cohort = Cohort.objects.create(
            team=self.team,
            name="static cohort",
            is_static=True,
            query=PERSONS_HOGQL_QUERY,
            is_calculating=True,
            pending_population_mode=CohortPopulationMode.REPLACE,
            population_claimed_at=timezone.now().replace(microsecond=0),
        )
        insert_cohort_from_query.push_request(retries=0, called_directly=False, is_eager=True)
        try:
            with (
                patch(QUERY_CH_INSERT_PATH, return_value=1),
                patch(PG_SYNC_PATH, side_effect=_rpc_error(grpc.StatusCode.UNAVAILABLE)),
                self.assertRaises(Retry) as scheduled,
            ):
                insert_cohort_from_query.run(cohort.id, self.team.pk)
            first_marker = Cohort.objects.get(pk=cohort.pk).population_marker
            assert first_marker is not None
            if takeover is not None:
                Cohort.objects.filter(pk=cohort.pk).update(**takeover(first_marker))
            run_state = ("is_calculating", "pending_population_mode", "population_marker", "errors_calculating")
            stored_before_retry = Cohort.objects.values_list(*run_state).get(pk=cohort.pk)
            history_rows_before_retry = CohortCalculationHistory.objects.filter(cohort=cohort).count()

            with patch(QUERY_CH_INSERT_PATH) as mock_insert_ch, patch(PG_SYNC_PATH, return_value=1) as mock_sync:
                insert_cohort_from_query.run(cohort.id, self.team.pk, **scheduled.exception.sig.kwargs)
        finally:
            insert_cohort_from_query.pop_request()

        mock_insert_ch.assert_not_called()
        cohort.refresh_from_db()
        if takeover is not None:
            # The retry belongs to a run the cohort no longer runs, so it writes nothing and leaves every run field,
            # the error count and the history as the newer owner (or the sweep) left them.
            mock_sync.assert_not_called()
            self.assertEqual(Cohort.objects.values_list(*run_state).get(pk=cohort.pk), stored_before_retry)
            self.assertEqual(CohortCalculationHistory.objects.filter(cohort=cohort).count(), history_rows_before_retry)
        else:
            self.assertEqual(mock_sync.call_args.kwargs["replace_marker"], first_marker)
            self.assertEqual((cohort.is_calculating, cohort.population_marker), (False, None))

    def test_query_replace_that_matches_nobody_keeps_every_member(self) -> None:
        # A misspelled property is the likely cause. Pruning to an empty result would drop every member, and every
        # flag and survey built on the cohort would change at once.
        member = create_person(team=self.team, distinct_ids=["member"], uuid=uuid4())
        cohort = Cohort.objects.create(
            team=self.team,
            name="static cohort",
            is_static=True,
            query={"kind": "HogQLQuery", "query": "SELECT id FROM persons WHERE properties.tag = 'nobody has this'"},
        )
        cohort.insert_users_list_by_uuid([str(member.uuid)], team_id=self.team.pk)
        _claim_replace(cohort)

        # Past the member's row, so the marker mints without waiting out the second it was stamped in.
        with time_machine.travel(timezone.now() + timedelta(seconds=10), tick=False):
            insert_cohort_from_query(cohort.id, self.team.pk)

        cohort.refresh_from_db()
        history = CohortCalculationHistory.objects.filter(cohort=cohort).latest("started_at")
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [member.id])
        # Refused, not retried: the run ends, counts as a failed calculation so the user sees why on the cohort,
        # but does not send to error tracking.
        self.assertEqual(
            (
                cohort.is_calculating,
                cohort.pending_population_mode,
                cohort.population_marker,
                cohort.errors_calculating,
                history.error_code,
                history.mode,
            ),
            (False, None, None, 1, "empty_replace", CohortPopulationMode.REPLACE),
        )
        self.assertEqual(
            history.error,
            "The replace was stopped because the query matched no persons, so the cohort kept its existing members. "
            "Check the query for a typo, such as a misspelled property name.",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort.id}/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["errors_calculating"], 1)
        self.assertIs(payload["is_calculating"], False)
        self.assertEqual(
            payload["last_error_message"],
            "The replace was stopped because the query matched no persons, so the cohort kept its existing members. "
            "Check the query for a typo, such as a misspelled property name.",
        )

    def test_query_replace_returning_unknown_uuid_keeps_every_member(self) -> None:
        from products.cohorts.backend.models import util as cohort_util

        member = create_person(team=self.team, distinct_ids=["member"], uuid=uuid4())
        flush_persons_and_events()
        unknown_uuid = uuid4()
        cohort = Cohort.objects.create(
            team=self.team,
            name="static cohort",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT toUUID('{unknown_uuid}') AS person_id FROM persons LIMIT 1"},
        )
        cohort.insert_users_list_by_uuid([str(member.uuid)], team_id=self.team.pk)
        _claim_replace(cohort)

        with (
            time_machine.travel(timezone.now() + timedelta(seconds=10), tick=False),
            patch(
                "products.cohorts.backend.models.util.insert_cohort_people_into_pg",
                wraps=cohort_util.insert_cohort_people_into_pg,
            ) as mock_copy_to_pg,
        ):
            insert_cohort_from_query(cohort.id, self.team.pk)

        mock_copy_to_pg.assert_called_once()
        cohort.refresh_from_db()
        history = CohortCalculationHistory.objects.filter(cohort=cohort).latest("started_at")
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [member.id])
        self.assertEqual(
            (
                cohort.is_calculating,
                cohort.pending_population_mode,
                cohort.population_marker,
                cohort.errors_calculating,
                history.error_code,
                history.mode,
            ),
            (False, None, None, 1, "empty_replace", CohortPopulationMode.REPLACE),
        )

    def test_query_replace_with_unknown_uuid_and_post_floor_add_still_refuses_to_prune(self) -> None:
        from products.cohorts.backend.models import util as cohort_util

        existing = create_person(team=self.team, distinct_ids=["existing"], uuid=uuid4())
        manual = create_person(team=self.team, distinct_ids=["manual"], uuid=uuid4())
        flush_persons_and_events()
        unknown_uuid = uuid4()
        start = timezone.now().replace(microsecond=0)

        with (
            time_machine.travel(start, tick=False) as clock,
            patch(
                "products.cohorts.backend.models.util.insert_cohort_people_into_pg",
                wraps=cohort_util.insert_cohort_people_into_pg,
            ) as mock_copy_to_pg,
        ):
            cohort = Cohort.objects.create(
                team=self.team,
                name="static cohort",
                is_static=True,
                query={
                    "kind": "HogQLQuery",
                    "query": f"SELECT toUUID('{unknown_uuid}') AS person_id FROM persons LIMIT 1",
                },
            )
            cohort.insert_users_list_by_uuid([str(existing.uuid)], team_id=self.team.pk)

            clock.shift(10)
            _claim_replace(cohort)

            # Added after the replace was claimed, so it lands in the copied batch via the floor rule
            # while only unknown_uuid carries the replace marker.
            clock.shift(5)
            cohort.insert_users_list_by_uuid([str(manual.uuid)], team_id=self.team.pk, save_state=False)

            clock.shift(5)
            insert_cohort_from_query(cohort.id, self.team.pk)

        mock_copy_to_pg.assert_called_once()
        cohort.refresh_from_db()
        history = CohortCalculationHistory.objects.filter(cohort=cohort).latest("started_at")
        self.assertEqual(
            set(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk)), {existing.id, manual.id}
        )
        self.assertEqual(
            (
                cohort.is_calculating,
                cohort.pending_population_mode,
                cohort.population_marker,
                cohort.errors_calculating,
                history.error_code,
                history.mode,
            ),
            (False, None, None, 1, "empty_replace", CohortPopulationMode.REPLACE),
        )

    def test_query_replace_keeps_manual_add_stamped_one_second_before_claim(self) -> None:
        run = uuid4().hex[:8]
        pre_existing, concurrent_add, matched = (
            create_person(
                team=self.team, distinct_ids=[f"{run}-{name}"], properties={"tag": f"{run}-{tag}"}, uuid=uuid4()
            )
            for name, tag in (("pre", "old"), ("add", "old"), ("match", "match"))
        )
        flush_persons_and_events()
        start = timezone.now().replace(microsecond=0)
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{run}-match'"},
        )

        with time_machine.travel(start, tick=False) as clock:
            cohort.insert_users_list_by_uuid([str(pre_existing.uuid)], team_id=self.team.pk)
            clock.shift(20)
            cohort.insert_users_list_by_uuid([str(concurrent_add.uuid)], team_id=self.team.pk)
            clock.shift(1)
            claimed_at = timezone.now().replace(microsecond=0)
            _claim_replace(cohort, claimed_at=claimed_at)
            clock.shift(10)
            insert_cohort_from_query(cohort.id, self.team.pk)

        cohort.refresh_from_db()
        self.assertEqual(cohort.last_replace_floor, claimed_at - REPLACE_FLOOR_CLOCK_MARGIN)
        self.assertEqual(
            set(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk)),
            {matched.id, concurrent_add.id},
        )

    def test_query_replace_without_population_claimed_at_fails_and_keeps_members(self) -> None:
        member = create_person(team=self.team, distinct_ids=["member"], uuid=uuid4())
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query=PERSONS_HOGQL_QUERY,
        )
        cohort.insert_users_list_by_uuid([str(member.uuid)], team_id=self.team.pk)
        Cohort.objects.filter(pk=cohort.pk).update(
            is_calculating=True,
            pending_population_mode=CohortPopulationMode.REPLACE,
            population_claimed_at=None,
        )

        with (
            patch("products.cohorts.backend.models.util.mint_population_marker") as mock_mint,
            patch(QUERY_CH_INSERT_PATH) as mock_insert_ch,
            patch("posthog.tasks.calculate_cohort.capture_exception") as mock_capture,
        ):
            insert_cohort_from_query(cohort.id, self.team.pk)

        mock_mint.assert_not_called()
        mock_insert_ch.assert_not_called()
        mock_capture.assert_called_once()
        cohort.refresh_from_db()
        history = CohortCalculationHistory.objects.filter(cohort=cohort).latest("started_at")
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [member.id])
        self.assertEqual(
            (
                cohort.is_calculating,
                cohort.pending_population_mode,
                cohort.population_marker,
                cohort.errors_calculating,
                history.error_code,
                history.error,
            ),
            (
                False,
                None,
                None,
                1,
                CohortErrorCode.POPULATION_CLAIM_INCOMPLETE,
                get_friendly_error_message(CohortErrorCode.POPULATION_CLAIM_INCOMPLETE, will_retry=False),
            ),
        )

    def test_query_replace_stopped_at_entry_when_flag_is_off(self) -> None:
        self.mock_replace_flag.return_value = False
        member = create_person(team=self.team, distinct_ids=["member"], uuid=uuid4())
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query=PERSONS_HOGQL_QUERY,
        )
        cohort.insert_users_list_by_uuid([str(member.uuid)], team_id=self.team.pk)
        _claim_replace(cohort)

        with (
            patch("products.cohorts.backend.models.util.mint_population_marker") as mock_mint,
            patch(QUERY_CH_INSERT_PATH) as mock_insert_ch,
            patch(PG_SYNC_PATH) as mock_sync,
            patch("posthog.tasks.calculate_cohort.capture_exception") as mock_capture,
        ):
            insert_cohort_from_query(cohort.id, self.team.pk)

        mock_mint.assert_not_called()
        mock_insert_ch.assert_not_called()
        mock_sync.assert_not_called()
        mock_capture.assert_not_called()
        cohort.refresh_from_db()
        history = CohortCalculationHistory.objects.filter(cohort=cohort).latest("started_at")
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [member.id])
        self.assertEqual(
            (
                cohort.is_calculating,
                cohort.pending_population_mode,
                cohort.population_marker,
                cohort.population_claimed_at,
                cohort.errors_calculating,
                history.error_code,
                history.error,
            ),
            (
                False,
                None,
                None,
                None,
                1,
                CohortErrorCode.REPLACE_DISABLED,
                get_friendly_error_message(CohortErrorCode.REPLACE_DISABLED, will_retry=False),
            ),
        )

    def test_query_replace_flag_lookup_error_fails_closed(self) -> None:
        from products.cohorts.backend.models.util import is_static_cohort_replace_enabled

        member = create_person(team=self.team, distinct_ids=["member"], uuid=uuid4())
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query=PERSONS_HOGQL_QUERY,
        )
        cohort.insert_users_list_by_uuid([str(member.uuid)], team_id=self.team.pk)
        _claim_replace(cohort)

        with (
            patch(
                "posthog.tasks.calculate_cohort.is_static_cohort_replace_enabled",
                new=is_static_cohort_replace_enabled,
            ),
            patch("posthoganalytics.get_feature_flag", side_effect=RuntimeError("flag service down")),
            patch(QUERY_CH_INSERT_PATH) as mock_insert_ch,
        ):
            insert_cohort_from_query(cohort.id, self.team.pk)

        mock_insert_ch.assert_not_called()
        cohort.refresh_from_db()
        history = CohortCalculationHistory.objects.filter(cohort=cohort).latest("started_at")
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [member.id])
        self.assertEqual(
            (cohort.is_calculating, cohort.pending_population_mode, history.error_code),
            (False, None, CohortErrorCode.REPLACE_DISABLED),
        )

    def test_query_replace_stopped_before_copy_when_flag_turns_off_during_clickhouse_insert(self) -> None:
        self.mock_replace_flag.side_effect = [True, False]
        member = create_person(team=self.team, distinct_ids=["member"], uuid=uuid4())
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query=PERSONS_HOGQL_QUERY,
        )
        cohort.insert_users_list_by_uuid([str(member.uuid)], team_id=self.team.pk)
        _claim_replace(cohort)

        with (
            patch(QUERY_CH_INSERT_PATH, return_value=1) as mock_insert_ch,
            patch(PG_SYNC_PATH) as mock_sync,
            patch("products.cohorts.backend.models.util.prune_members_absent_from_replace") as mock_pg_prune,
        ):
            insert_cohort_from_query(cohort.id, self.team.pk)

        mock_insert_ch.assert_called_once()
        mock_sync.assert_not_called()
        mock_pg_prune.assert_not_called()
        cohort.refresh_from_db()
        history = CohortCalculationHistory.objects.filter(cohort=cohort).latest("started_at")
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [member.id])
        self.assertEqual(
            (cohort.is_calculating, cohort.pending_population_mode, history.error_code),
            (False, None, CohortErrorCode.REPLACE_DISABLED),
        )

    def test_query_replace_marker_retry_converges_when_flag_is_turned_off(self) -> None:
        run = uuid4().hex[:8]
        stale = create_person(
            team=self.team, distinct_ids=[f"{run}-stale"], properties={"tag": f"{run}-old"}, uuid=uuid4()
        )
        kept = create_person(
            team=self.team, distinct_ids=[f"{run}-kept"], properties={"tag": f"{run}-keep"}, uuid=uuid4()
        )
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{run}-keep'"},
        )
        start = timezone.now().replace(microsecond=0)

        with time_machine.travel(start, tick=False) as clock:
            cohort.insert_users_list_by_uuid([str(stale.uuid)], team_id=self.team.pk)
            clock.shift(10)
            _claim_replace(cohort)
            clock.shift(10)
            insert_cohort_from_query.push_request(retries=0, called_directly=False, is_eager=True)
            try:
                with (
                    patch(
                        "products.cohorts.backend.models.util.prune_members_absent_from_replace",
                        side_effect=ClickHouseAtCapacity("transient"),
                    ),
                    self.assertRaises(Retry) as scheduled,
                ):
                    insert_cohort_from_query.run(cohort.id, self.team.pk)
                self.assertIn("replace_marker", scheduled.exception.sig.kwargs)
                self.assertTrue(scheduled.exception.sig.kwargs["pg_membership_written"])

                # Turn off the kill switch before the retry runs; because this lineage already wrote
                # replace rows to Postgres, it finishes converging instead of stranding stale members.
                self.mock_replace_flag.return_value = False
                clock.shift(10)
                insert_cohort_from_query.run(cohort.id, self.team.pk, **scheduled.exception.sig.kwargs)
            finally:
                insert_cohort_from_query.pop_request()

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertIsNone(cohort.pending_population_mode)
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [kept.id])

    def test_query_replace_marker_retry_without_pg_writes_stops_and_cleans_up_when_flag_is_turned_off(self) -> None:
        run = uuid4().hex[:8]
        stale = create_person(
            team=self.team, distinct_ids=[f"{run}-stale"], properties={"tag": f"{run}-old"}, uuid=uuid4()
        )
        create_person(team=self.team, distinct_ids=[f"{run}-kept"], properties={"tag": f"{run}-keep"}, uuid=uuid4())
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{run}-keep'"},
        )
        start = timezone.now().replace(microsecond=0)

        with time_machine.travel(start, tick=False) as clock:
            cohort.insert_users_list_by_uuid([str(stale.uuid)], team_id=self.team.pk)
            clock.shift(10)
            _claim_replace(cohort)
            clock.shift(10)
            insert_cohort_from_query.push_request(retries=0, called_directly=False, is_eager=True)
            try:
                with (
                    patch(PG_SYNC_PATH, side_effect=ClickHouseAtCapacity("transient")),
                    self.assertRaises(Retry) as scheduled,
                ):
                    insert_cohort_from_query.run(cohort.id, self.team.pk)
                self.assertIn("replace_marker", scheduled.exception.sig.kwargs)
                self.assertFalse(scheduled.exception.sig.kwargs["pg_membership_written"])

                self.mock_replace_flag.return_value = False
                clock.shift(10)
                insert_cohort_from_query.run(cohort.id, self.team.pk, **scheduled.exception.sig.kwargs)
            finally:
                insert_cohort_from_query.pop_request()

        cohort.refresh_from_db()
        history = CohortCalculationHistory.objects.filter(cohort=cohort).latest("started_at")
        self.assertEqual(
            (cohort.is_calculating, cohort.pending_population_mode, history.error_code),
            (False, None, CohortErrorCode.REPLACE_DISABLED),
        )
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [stale.id])
        self.assertEqual(_static_cohort_rows(self.team.pk, cohort.pk), [(str(stale.uuid), 0)])

    def test_sweep_redispatched_replace_stopped_when_flag_is_off(self) -> None:
        now = timezone.now().replace(microsecond=0)
        member = create_person(team=self.team, distinct_ids=["member"], uuid=uuid4())
        cohort = Cohort.objects.create(
            team=self.team,
            name="stuck replace",
            is_static=True,
            is_calculating=True,
            query=PERSONS_HOGQL_QUERY,
            pending_population_mode=CohortPopulationMode.REPLACE,
            population_marker=now - relativedelta(hours=2),
            population_claimed_at=now - relativedelta(hours=6),
        )
        cohort.insert_users_list_by_uuid([str(member.uuid)], team_id=self.team.pk, save_state=False)
        Cohort.objects.filter(pk=cohort.pk).update(created_at=now - relativedelta(hours=6))

        with patch("posthog.tasks.calculate_cohort.insert_cohort_from_query.delay") as mock_delay:
            reset_stuck_cohorts()
            mock_delay.assert_called_once_with(cohort.pk, self.team.pk)

        self.mock_replace_flag.return_value = False
        with patch(QUERY_CH_INSERT_PATH) as mock_insert_ch:
            insert_cohort_from_query(cohort.id, self.team.pk)

        mock_insert_ch.assert_not_called()
        cohort.refresh_from_db()
        history = CohortCalculationHistory.objects.filter(cohort=cohort).latest("started_at")
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [member.id])
        self.assertEqual(
            (cohort.is_calculating, cohort.pending_population_mode, history.error_code),
            (False, None, CohortErrorCode.REPLACE_DISABLED),
        )

    def test_query_append_still_runs_when_replace_flag_is_off(self) -> None:
        self.mock_replace_flag.return_value = False
        run = uuid4().hex[:8]
        existing = create_person(
            team=self.team, distinct_ids=[f"{run}-existing"], properties={"tag": f"{run}-old"}, uuid=uuid4()
        )
        new = create_person(team=self.team, distinct_ids=[f"{run}-new"], properties={"tag": f"{run}-new"}, uuid=uuid4())
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="static append",
            is_static=True,
            is_calculating=True,
            pending_population_mode=CohortPopulationMode.APPEND,
            query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{run}-new'"},
        )
        cohort.insert_users_list_by_uuid([str(existing.uuid)], team_id=self.team.pk, save_state=False)

        insert_cohort_from_query(cohort.id, self.team.pk)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertIsNone(cohort.pending_population_mode)
        self.assertEqual(set(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk)), {existing.id, new.id})

    def test_junk_uuid_refusal_deletes_attempt_rows_from_clickhouse(self) -> None:
        existing = create_person(team=self.team, distinct_ids=["existing"], uuid=uuid4())
        flush_persons_and_events()
        unknown_uuid = uuid4()
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT toUUID('{unknown_uuid}') AS person_id FROM persons LIMIT 1"},
        )
        start = timezone.now().replace(microsecond=0)
        cohort.insert_users_list_by_uuid([str(existing.uuid)], team_id=self.team.pk)
        _claim_replace(cohort, claimed_at=start)

        with time_machine.travel(start + timedelta(seconds=10), tick=False):
            insert_cohort_from_query(cohort.id, self.team.pk)

        self.assertEqual(_static_cohort_rows(self.team.pk, cohort.pk), [(str(existing.uuid), 0)])
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [existing.id])

    def test_pre_copy_kill_switch_stop_deletes_attempt_rows_from_clickhouse(self) -> None:
        self.mock_replace_flag.side_effect = [True, False]
        run = uuid4().hex[:8]
        existing = create_person(
            team=self.team, distinct_ids=[f"{run}-old"], properties={"tag": f"{run}-old"}, uuid=uuid4()
        )
        create_person(team=self.team, distinct_ids=[f"{run}-new"], properties={"tag": f"{run}-new"}, uuid=uuid4())
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{run}-new'"},
        )
        start = timezone.now().replace(microsecond=0)
        cohort.insert_users_list_by_uuid([str(existing.uuid)], team_id=self.team.pk)
        _claim_replace(cohort, claimed_at=start)

        with time_machine.travel(start + timedelta(seconds=10), tick=False):
            insert_cohort_from_query(cohort.id, self.team.pk)

        self.assertEqual(_static_cohort_rows(self.team.pk, cohort.pk), [(str(existing.uuid), 0)])
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [existing.id])
        history = CohortCalculationHistory.objects.filter(cohort=cohort).latest("started_at")
        self.assertEqual(history.error_code, CohortErrorCode.REPLACE_DISABLED)

    def test_system_exit_after_replace_insert_deletes_attempt_rows_from_clickhouse(self) -> None:
        run = uuid4().hex[:8]
        existing = create_person(
            team=self.team, distinct_ids=[f"{run}-old"], properties={"tag": f"{run}-old"}, uuid=uuid4()
        )
        create_person(team=self.team, distinct_ids=[f"{run}-new"], properties={"tag": f"{run}-new"}, uuid=uuid4())
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{run}-new'"},
        )
        start = timezone.now().replace(microsecond=0)
        cohort.insert_users_list_by_uuid([str(existing.uuid)], team_id=self.team.pk)
        _claim_replace(cohort, claimed_at=start)

        with (
            time_machine.travel(start + timedelta(seconds=10), tick=False),
            patch(PG_SYNC_PATH, side_effect=SystemExit(1)),
            self.assertRaises(SystemExit),
        ):
            insert_cohort_from_query(cohort.id, self.team.pk)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertIsNone(cohort.pending_population_mode)
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [existing.id])
        self.assertEqual(_static_cohort_rows(self.team.pk, cohort.pk), [(str(existing.uuid), 0)])

    def test_entry_kill_switch_stop_after_failed_insert_deletes_earlier_attempts_rows(self) -> None:
        run = uuid4().hex[:8]
        existing = create_person(
            team=self.team, distinct_ids=[f"{run}-old"], properties={"tag": f"{run}-old"}, uuid=uuid4()
        )
        create_person(team=self.team, distinct_ids=[f"{run}-new"], properties={"tag": f"{run}-new"}, uuid=uuid4())
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{run}-new'"},
        )
        start = timezone.now().replace(microsecond=0)
        cohort.insert_users_list_by_uuid([str(existing.uuid)], team_id=self.team.pk)
        _claim_replace(cohort, claimed_at=start)

        real_insert = insert_cohort_query_actors_into_ch

        def insert_then_fail(*args: Any, **kwargs: Any) -> int:
            real_insert(*args, **kwargs)
            raise InternalCHQueryError("unknown status of insert", code=319)

        with time_machine.travel(start + timedelta(seconds=10), tick=False) as clock:
            insert_cohort_from_query.push_request(retries=0, called_directly=False, is_eager=True)
            try:
                with (
                    patch(QUERY_CH_INSERT_PATH, side_effect=insert_then_fail),
                    self.assertRaises(Retry) as scheduled,
                ):
                    insert_cohort_from_query.run(cohort.id, self.team.pk)
                self.assertNotIn("replace_marker", scheduled.exception.sig.kwargs)

                self.mock_replace_flag.return_value = False
                clock.shift(10)
                insert_cohort_from_query.run(cohort.id, self.team.pk, **scheduled.exception.sig.kwargs)
            finally:
                insert_cohort_from_query.pop_request()

        self.assertEqual(_static_cohort_rows(self.team.pk, cohort.pk), [(str(existing.uuid), 0)])
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [existing.id])

    def test_mid_copy_failure_keeps_clickhouse_rows_so_postgres_remains_a_subset(self) -> None:
        run = uuid4().hex[:8]
        # Deterministic ascending UUIDs in both high and low halves so ClickHouse ORDER BY person_id splits cleanly.
        uuids = [UUID(f"{int(run, 16):08x}-0000-0000-0000-{i:012x}") for i in range(1, 4)]
        persons = [
            create_person(team=self.team, distinct_ids=[f"{run}-{i}"], properties={"tag": f"{run}-in"}, uuid=u)
            for i, u in enumerate(uuids)
        ]
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{run}-in'"},
        )
        start = timezone.now().replace(microsecond=0)
        _claim_replace(cohort, claimed_at=start)

        real_insert_batch = Cohort._insert_batch_via_personhog
        batch_calls = 0

        def write_first_batch_then_fail(
            cohort_self: Cohort, batch: list[str], insert_in_clickhouse: bool, *, team_id: int
        ) -> set[str]:
            nonlocal batch_calls
            batch_calls += 1
            if batch_calls == 2:
                raise RuntimeError("mid-copy failure")
            return real_insert_batch(cohort_self, batch, insert_in_clickhouse, team_id=team_id)

        with (
            time_machine.travel(start + timedelta(seconds=10), tick=False),
            patch("products.cohorts.backend.models.util.CH_PAGE_SIZE", 2),
            patch.object(Cohort, "_insert_batch_via_personhog", autospec=True, side_effect=write_first_batch_then_fail),
        ):
            insert_cohort_from_query(cohort.id, self.team.pk)

        # First batch wrote p0 to Postgres; ClickHouse keeps all three rows so PG stays a subset of CH.
        self.assertEqual(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk), [persons[0].id])
        ch_rows = sync_execute(
            "SELECT DISTINCT person_id FROM person_static_cohort WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s AND _offset = %(offset)s",
            {"team_id": self.team.pk, "cohort_id": cohort.pk, "offset": REPLACE_ROW_OFFSET},
        )
        self.assertEqual({str(row[0]) for row in ch_rows}, {str(u) for u in uuids})

    def test_marker_carrying_retry_failing_before_copy_keeps_predecessor_clickhouse_rows(self) -> None:
        run = uuid4().hex[:8]
        matched = create_person(
            team=self.team, distinct_ids=[f"{run}-m"], properties={"tag": f"{run}-in"}, uuid=uuid4()
        )
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{run}-in'"},
        )
        start = timezone.now().replace(microsecond=0)
        _claim_replace(cohort, claimed_at=start)

        with time_machine.travel(start + timedelta(seconds=10), tick=False) as clock:
            insert_cohort_from_query.push_request(retries=0, called_directly=False, is_eager=True)
            try:
                with (
                    patch(PG_SYNC_PATH, side_effect=ClickHouseAtCapacity("transient")),
                    self.assertRaises(Retry) as scheduled,
                ):
                    insert_cohort_from_query.run(cohort.id, self.team.pk)
                self.assertIn("replace_marker", scheduled.exception.sig.kwargs)

                insert_cohort_from_query.pop_request()
                insert_cohort_from_query.push_request(
                    retries=STATIC_POPULATION_MAX_RETRIES, called_directly=False, is_eager=True
                )
                clock.shift(10)
                with patch(PG_SYNC_PATH, side_effect=RuntimeError("fatal copy failure")):
                    insert_cohort_from_query.run(cohort.id, self.team.pk, **scheduled.exception.sig.kwargs)
            finally:
                insert_cohort_from_query.pop_request()

        ch_rows = sync_execute(
            "SELECT DISTINCT person_id FROM person_static_cohort WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s AND _offset = %(offset)s",
            {"team_id": self.team.pk, "cohort_id": cohort.pk, "offset": REPLACE_ROW_OFFSET},
        )
        self.assertEqual({str(row[0]) for row in ch_rows}, {str(matched.uuid)})

    def test_resync_stopped_when_replace_claims_cohort_between_read_and_lock(self) -> None:
        # A concurrent PATCH claim arriving after the task starts must fence out an append_only resync before it
        # writes members or opens a history row.
        cohort = Cohort.objects.create(
            team=self.team,
            name="static cohort",
            is_static=True,
            query=PERSONS_HOGQL_QUERY,
        )

        def claim_replace_concurrently(*args: Any, **kwargs: Any) -> None:
            _claim_replace(cohort)

        with (
            patch("posthog.tasks.calculate_cohort._tag_population_queries", side_effect=claim_replace_concurrently),
            patch(QUERY_CH_INSERT_PATH) as mock_insert_ch,
        ):
            insert_cohort_from_query(cohort.id, self.team.pk, append_only=True)

        mock_insert_ch.assert_not_called()
        cohort.refresh_from_db()
        self.assertEqual(
            (cohort.is_calculating, cohort.pending_population_mode, cohort.errors_calculating),
            (True, CohortPopulationMode.REPLACE, 0),
        )
        self.assertFalse(CohortCalculationHistory.objects.filter(cohort=cohort).exists())

    @parameterized.expand(
        [
            ("replace_running", True),
            # The sweep released the run and its redispatch hasn't started: a re-sync claiming the cohort here would
            # leave it calculating with nothing running.
            ("replace_waiting_after_a_sweep_reset", False),
        ]
    )
    def test_a_resync_that_starts_after_a_replace_was_requested_writes_nothing(
        self, _name: str, is_calculating: bool
    ) -> None:
        # The staff re-sync dispatches without a claim and only adds members. A replace requested after it was
        # queued belongs to its own task, so the re-sync must neither run it nor touch the run's fields.
        cohort = Cohort.objects.create(
            team=self.team,
            name="static cohort",
            is_static=True,
            query={"kind": "HogQLQuery", "query": "SELECT id FROM persons"},
        )
        Cohort.objects.filter(pk=cohort.pk).update(
            is_calculating=is_calculating, pending_population_mode=CohortPopulationMode.REPLACE
        )

        with patch("products.cohorts.backend.models.util.insert_cohort_query_actors_into_ch") as mock_insert_ch:
            insert_cohort_from_query(cohort.id, self.team.pk, append_only=True)

        mock_insert_ch.assert_not_called()
        cohort.refresh_from_db()
        self.assertEqual(
            (cohort.is_calculating, cohort.pending_population_mode, cohort.errors_calculating),
            (is_calculating, CohortPopulationMode.REPLACE, 0),
        )
        self.assertFalse(CohortCalculationHistory.objects.filter(cohort=cohort).exists())

    def test_a_replace_retry_after_a_failed_insert_does_not_carry_a_marker(self) -> None:
        # The insert's rows may be partly written at the old marker, so the retry must mint a fresh one, which puts
        # those rows below its prune, instead of resuming at the old marker.
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query=PERSONS_HOGQL_QUERY,
            is_calculating=True,
            pending_population_mode=CohortPopulationMode.REPLACE,
            population_claimed_at=timezone.now().replace(microsecond=0),
        )

        insert_cohort_from_query.push_request(retries=0, called_directly=False, is_eager=True)
        try:
            with (
                patch(QUERY_CH_INSERT_PATH, side_effect=InternalCHQueryError("unknown status of insert", code=319)),
                self.assertRaises(Retry) as scheduled,
            ):
                insert_cohort_from_query.run(cohort.id, self.team.pk)
        finally:
            insert_cohort_from_query.pop_request()

        self.assertNotIn("replace_marker", scheduled.exception.sig.kwargs)
        self.assertFalse(scheduled.exception.sig.kwargs["ch_insert_done"])

    def test_a_retried_replace_keeps_adds_since_the_request_and_drops_its_failed_attempt(self) -> None:
        # Attempt 1 writes its matches, then fails, so attempt 2 mints a newer marker under an edited query.
        # Adds made before attempt 1 and between the attempts must survive. Attempt 1's rows must not: neither
        # a match only attempt 1 made, nor the duplicate rows it left for a person both attempts match.
        # Tags unique to this run: ClickHouse keeps persons from earlier tests in the same team.
        run = uuid4().hex[:8]
        a, s, p, q, r = (
            create_person(team=self.team, distinct_ids=[name], properties={"tag": f"{run}-{tag}"}, uuid=uuid4())
            for name, tag in (("a", "a"), ("s", "s"), ("p", "x"), ("q", "x"), ("r", "x"))
        )
        flush_persons_and_events()
        start = timezone.now().replace(microsecond=0)
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query={
                "kind": "HogQLQuery",
                "query": f"SELECT id FROM persons WHERE properties.tag IN ('{run}-a', '{run}-s')",
            },
        )
        real_insert = insert_cohort_query_actors_into_ch

        def insert_then_fail(*args: Any, **kwargs: Any) -> int:
            real_insert(*args, **kwargs)
            raise InternalCHQueryError("unknown status of insert", code=319)

        with time_machine.travel(start, tick=False) as clock:
            # r was a member before the request and matches neither query.
            cohort.insert_users_list_by_uuid([str(r.uuid)], team_id=self.team.pk)
            clock.shift(10)
            _claim_replace(cohort)
            clock.shift(10)
            cohort.insert_users_list_by_uuid([str(p.uuid)], team_id=self.team.pk, save_state=False)
            clock.shift(10)
            insert_cohort_from_query.push_request(retries=0, called_directly=False, is_eager=True)
            try:
                with (
                    patch(QUERY_CH_INSERT_PATH, side_effect=insert_then_fail),
                    self.assertRaises(Retry) as scheduled,
                ):
                    insert_cohort_from_query.run(cohort.id, self.team.pk)
            finally:
                insert_cohort_from_query.pop_request()
            clock.shift(10)
            cohort.insert_users_list_by_uuid([str(q.uuid)], team_id=self.team.pk, save_state=False)
            Cohort.objects.filter(pk=cohort.pk).update(
                query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{run}-a'"}
            )
            clock.shift(10)
            insert_cohort_from_query.run(cohort.id, self.team.pk, **scheduled.exception.sig.kwargs)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(set(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk)), {a.id, p.id, q.id})
                # One flagged row for the match, and the adds keep _offset 0: only the replace's insert sets the flag.
        self.assertEqual(
            sorted(_static_cohort_rows(self.team.pk, cohort.pk)),
            sorted([(str(a.uuid), REPLACE_ROW_OFFSET), (str(p.uuid), 0), (str(q.uuid), 0)]),
        )

    def test_an_append_and_an_add_after_a_replace_ignore_the_rows_it_is_still_deleting(self) -> None:
        # In production the replace's ClickHouse delete applies asynchronously, so the rows it removes can linger.
        # An append or an add made before it applies must not read them as membership: the copy would put pruned
        # members back in Postgres, and the append's insert and the add would skip people the delete then removes.
        # Tags unique to this run: ClickHouse keeps persons from earlier tests in the same team.
        run = uuid4().hex[:8]
        a, p, s = (
            create_person(team=self.team, distinct_ids=[name], properties={"tag": f"{run}-{name}"}, uuid=uuid4())
            for name in ("a", "p", "s")
        )
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{run}-a'"},
        )
        start = timezone.now().replace(microsecond=0)
        with (
            time_machine.travel(start, tick=False) as clock,
            # The delete hasn't applied yet.
            patch("products.cohorts.backend.models.util.prune_stale_static_cohort_rows"),
        ):
            cohort.insert_users_list_by_uuid([str(p.uuid), str(s.uuid)], team_id=self.team.pk)
            clock.shift(10)
            _claim_replace(cohort)
            clock.shift(10)
            insert_cohort_from_query(cohort.id, self.team.pk)
            cohort.refresh_from_db()
            self.assertIsNotNone(cohort.last_replace_marker)
            self.assertEqual(set(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk)), {a.id})

            # An append that matches p again, and an add of s, both before the replace's delete applies.
            clock.shift(10)
            Cohort.objects.filter(pk=cohort.pk).update(
                is_calculating=True,
                pending_population_mode=CohortPopulationMode.APPEND,
                query={
                    "kind": "HogQLQuery",
                    "query": f"SELECT id FROM persons WHERE properties.tag IN ('{run}-a', '{run}-p')",
                },
            )
            insert_cohort_from_query(cohort.id, self.team.pk)
            cohort.refresh_from_db()
            # s was pruned and the append doesn't match it, so the copy must not bring it back.
            self.assertEqual(set(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk)), {a.id, p.id})
            clock.shift(10)
            cohort.insert_users_list_by_uuid([str(s.uuid)], team_id=self.team.pk, save_state=False)

        # Now the replace's delete applies. p and s were added again after it, so ClickHouse keeps them.
        prune_stale_static_cohort_rows(
            cohort.pk, team_id=self.team.pk, marker=cohort.last_replace_marker, floor=cohort.last_replace_floor
        )
        rows = sync_execute(
            "SELECT DISTINCT person_id FROM person_static_cohort WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s",
            {"team_id": self.team.pk, "cohort_id": cohort.pk},
        )
        self.assertEqual({str(row[0]) for row in rows}, {str(a.uuid), str(p.uuid), str(s.uuid)})
        self.assertEqual(set(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk)), {a.id, p.id, s.id})

    def test_replace_retry_after_partial_postgres_prune_converges(self) -> None:
        # A retry after a partial Postgres prune converges both stores exact.
        run = uuid4().hex[:8]
        kept, new, stale1, stale2 = (
            create_person(
                team=self.team, distinct_ids=[f"{run}-{name}"], properties={"tag": f"{run}-{tag}"}, uuid=uuid4()
            )
            for name, tag in (("kept", "in"), ("new", "in"), ("stale1", "out"), ("stale2", "out"))
        )
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="static replace retry",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{run}-in'"},
        )
        cohort.insert_users_list_by_uuid([str(kept.uuid), str(stale1.uuid), str(stale2.uuid)], team_id=self.team.pk)
        claimed_at = timezone.now().replace(microsecond=0) + timedelta(seconds=10)
        _claim_replace(cohort, claimed_at=claimed_at)

        real_delete = delete_cohort_members_by_person_ids
        delete_calls: list[list[int]] = []
        failed = False

        def delete_and_fail_on_first(team_id: int, cohort_id: int, person_ids: list[int]) -> int:
            nonlocal failed
            deleted = real_delete(team_id, cohort_id, person_ids)
            delete_calls.append(person_ids)
            if not failed:
                failed = True
                raise ClickHouseAtCapacity("transient failure after first page delete")
            return deleted

        insert_cohort_from_query.push_request(retries=0, called_directly=False, is_eager=True)
        try:
            with (
                time_machine.travel(claimed_at + timedelta(seconds=10), tick=False),
                patch("products.cohorts.backend.models.util.PRUNE_PAGE_SIZE", 1),
                patch("products.cohorts.backend.models.util.PRUNE_DELETE_CHUNK", 1),
                patch(
                    "products.cohorts.backend.models.util.delete_cohort_members_by_person_ids",
                    side_effect=delete_and_fail_on_first,
                ),
            ):
                with self.assertRaises(Retry) as scheduled:
                    insert_cohort_from_query.run(cohort.id, self.team.pk)

                self.assertEqual(len(delete_calls), 1)
                first_deleted = delete_calls[0]
                self.assertEqual(len(first_deleted), 1)
                remaining_stale = stale2.id if first_deleted[0] == stale1.id else stale1.id

                # The first attempt deleted only its first page from Postgres before failing, and ClickHouse
                # has not been pruned yet.
                pg_members_mid_run = set(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk))
                self.assertEqual(pg_members_mid_run, {kept.id, new.id, remaining_stale})

                marker_iso = scheduled.exception.sig.kwargs["replace_marker"]
                marker = datetime.fromisoformat(marker_iso)
                self.assertEqual(scheduled.exception.sig.kwargs["rows_written"], 2)
                self.assertTrue(scheduled.exception.sig.kwargs["ch_insert_done"])

                # Retry with the scheduled retry's own kwargs, carrying rows_written and replace_marker.
                insert_cohort_from_query.run(cohort.id, self.team.pk, **scheduled.exception.sig.kwargs)
        finally:
            insert_cohort_from_query.pop_request()

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertIsNone(cohort.pending_population_mode)
        self.assertIsNone(cohort.population_marker)
        self.assertEqual(cohort.errors_calculating, 0)

        # Both stores end exact:
        self.assertEqual(set(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk)), {kept.id, new.id})
        self.assertEqual(count_cohort_members(self.team.pk, cohort.pk), 2)
        self.assertEqual(cohort.count, 2)

        ch_rows = sync_execute(
            "SELECT person_id, count(), max(_timestamp) FROM person_static_cohort WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s GROUP BY person_id",
            {"team_id": self.team.id, "cohort_id": cohort.pk},
        )
        ch_stamps = {
            str(person_id): (count, _timestamp.replace(tzinfo=UTC)) for person_id, count, _timestamp in ch_rows
        }
        self.assertEqual(ch_stamps, {str(kept.uuid): (1, marker), str(new.uuid): (1, marker)})

    def test_replace_pins_membership_queries_to_data_cluster_when_team_uses_new_events_schema(self) -> None:
        from posthog.clickhouse.client.connection import Workload, get_kwargs_for_client
        from posthog.models.event.new_events_schema import use_new_events_schema
        from posthog.models.instance_setting import override_instance_config

        run = uuid4().hex[:8]
        kept, stale, manual = (
            create_person(
                team=self.team, distinct_ids=[f"{run}-{name}"], properties={"tag": f"{run}-{tag}"}, uuid=uuid4()
            )
            for name, tag in (("kept", "in"), ("stale", "out"), ("manual", "out"))
        )
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="new-events-schema replace",
            is_static=True,
            query={"kind": "HogQLQuery", "query": f"SELECT id FROM persons WHERE properties.tag = '{run}-in'"},
        )
        start = timezone.now().replace(microsecond=0)
        cohort.insert_users_list_by_uuid([str(kept.uuid), str(stale.uuid)], team_id=self.team.pk)

        recorded: list[tuple[str, str | None, int | None, dict[str, Any]]] = []
        real_sync_execute = sync_execute

        def spy_sync_execute(query: str, *args: Any, **kwargs: Any) -> Any:
            workload = kwargs.get("workload", Workload.DEFAULT)
            call_team_id = kwargs.get("team_id")
            with override_settings(
                CLICKHOUSE_EVENTS_OFFLINE_HOST="events-offline.invalid",
                CLICKHOUSE_OFFLINE_CLUSTER_HOST="data-offline.invalid",
            ):
                host = get_kwargs_for_client(workload=workload, team_id=call_team_id).get("host")
            recorded.append((query, host, call_team_id, dict(kwargs.get("settings") or {})))
            return real_sync_execute(query, *args, **kwargs)

        from products.cohorts.backend.models import util as cohort_util

        real_copy = cohort_util._copy_static_cohort_rows_to_pg
        manual_added = False

        def copy_after_manual_add(*args: Any, **kwargs: Any) -> tuple[int, bool]:
            nonlocal manual_added
            if not manual_added:
                manual_added = True
                cohort.insert_users_list_by_uuid([str(manual.uuid)], team_id=self.team.pk, save_state=False)
            return real_copy(*args, **kwargs)

        with (
            time_machine.travel(start + timedelta(seconds=10), tick=False) as clock,
            override_instance_config("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", str(self.team.pk)),
            patch("products.cohorts.backend.models.util.sync_execute", side_effect=spy_sync_execute),
            patch(
                "products.cohorts.backend.models.util._copy_static_cohort_rows_to_pg", side_effect=copy_after_manual_add
            ),
        ):
            self.assertTrue(use_new_events_schema(self.team.pk))
            _claim_replace(cohort)
            clock.shift(10)
            insert_cohort_from_query(cohort.id, self.team.pk)

        mint_calls = [c for c in recorded if "max(_timestamp)" in c[0]]
        copy_calls = [c for c in recorded if "ORDER BY person_id LIMIT" in c[0]]
        membership_calls = [c for c in recorded if "SELECT DISTINCT person_id" in c[0]]
        prune_calls = [c for c in recorded if c[0].lstrip().startswith("DELETE FROM")]
        insert_calls = [c for c in recorded if "INSERT INTO" in c[0] and "SELECT" in c[0]]

        self.assertTrue(mint_calls and copy_calls and membership_calls and prune_calls and insert_calls)
        for calls in (mint_calls, copy_calls, membership_calls, prune_calls):
            for _sql, host, call_team_id, _call_settings in calls:
                self.assertEqual(host, "data-offline.invalid")
                self.assertEqual(call_team_id, self.team.pk)

        self.assertEqual(insert_calls[0][1], "events-offline.invalid")
        self.assertEqual(insert_calls[0][2], self.team.pk)
        self.assertEqual(insert_calls[0][3].get("insert_distributed_sync"), 1)

        self.assertEqual(set(list_cohort_member_ids(team_id=self.team.pk, cohort_id=cohort.pk)), {kept.id, manual.id})
        ch_uuids = {
            str(row[0])
            for row in sync_execute(
                "SELECT DISTINCT person_id FROM person_static_cohort WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s",
                {"team_id": self.team.pk, "cohort_id": cohort.pk},
            )
        }
        self.assertEqual(ch_uuids, {str(kept.uuid), str(manual.uuid)})

    @parameterized.expand(
        [
            ("query_flipped_to_dynamic", insert_cohort_from_query, QUERY_CH_INSERT_PATH, {"is_static": False}),
            ("filters_flipped_to_dynamic", insert_cohort_from_filters, FILTERS_CH_INSERT_PATH, {"is_static": False}),
            ("query_deleted", insert_cohort_from_query, QUERY_CH_INSERT_PATH, {"is_static": True, "deleted": True}),
        ]
    )
    def test_static_population_skips_an_obsolete_cohort(
        self, _name: str, task: Task, ch_insert_path: str, cohort_state: dict[str, bool]
    ) -> None:
        # Flipping a static cohort to dynamic hands is_calculating to calculate_cohort_ch. An attempt
        # that wakes from its backoff afterwards must neither write members nor finalize that flag.
        cohort = Cohort.objects.create(team=self.team, name="static cohort", is_calculating=True, **cohort_state)

        with patch(ch_insert_path) as mock_insert_ch, patch(PG_SYNC_PATH) as mock_sync:
            task(cohort.id, self.team.pk)

        mock_insert_ch.assert_not_called()
        mock_sync.assert_not_called()
        cohort.refresh_from_db()
        self.assertTrue(cohort.is_calculating)
        self.assertIsNone(cohort.last_calculation)

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
            pending_population_mode=CohortPopulationMode.REPLACE,
            population_marker=now - relativedelta(hours=2),
        )
        # Set created_at to more than 1 hour ago (auto_now_add prevents setting on create)
        Cohort.objects.filter(pk=stuck_static_cohort.pk).update(created_at=now - relativedelta(hours=2))

        reset_stuck_cohorts()

        stuck_static_cohort.refresh_from_db()
        self.assertFalse(stuck_static_cohort.is_calculating)
        self.assertEqual(stuck_static_cohort.errors_calculating, 1)
        # The sweep clears the marker so a stale in-flight worker's finalize loses the fence,
        # but preserves the mode so the redispatched run still replaces and mints a fresh marker.
        self.assertEqual(stuck_static_cohort.pending_population_mode, CohortPopulationMode.REPLACE)
        self.assertIsNone(stuck_static_cohort.population_marker)

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
            pending_population_mode=CohortPopulationMode.REPLACE,
            population_marker=now - relativedelta(hours=2),
        )
        # Set created_at to more than 1 hour ago
        Cohort.objects.filter(pk=stuck_static_cohort.pk).update(created_at=now - relativedelta(hours=2))

        reset_stuck_cohorts()

        stuck_static_cohort.refresh_from_db()
        self.assertFalse(stuck_static_cohort.is_calculating)
        mock_insert_cohort_from_query.delay.assert_not_called()
        # Nothing will run the replace now, so a later edit must not inherit it.
        self.assertEqual(
            (stuck_static_cohort.pending_population_mode, stuck_static_cohort.population_marker), (None, None)
        )

    @parameterized.expand(
        [
            ("query_errored_within_the_hour", {"query": PERSONS_HOGQL_QUERY}, relativedelta(minutes=10), False),
            ("query_errored_over_an_hour_ago", {"query": PERSONS_HOGQL_QUERY}, relativedelta(hours=2), True),
            ("filters_errored_over_an_hour_ago", {"filters": PERSON_EMAIL_FILTERS}, relativedelta(hours=2), True),
        ]
    )
    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_filters")
    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_query")
    def test_reset_stuck_static_cohorts_honors_a_recent_error(
        self,
        _name: str,
        source_fields: dict,
        error_age: relativedelta,
        expect_reset: bool,
        mock_insert_cohort_from_query: MagicMock,
        mock_insert_cohort_from_filters: MagicMock,
    ) -> None:
        # A population task stamps last_error_at when it schedules a retry, so within the hour the
        # cohort sits in a backoff window, not stuck. Resetting it would dispatch a duplicate.
        mock_population_task = (
            mock_insert_cohort_from_query if "query" in source_fields else mock_insert_cohort_from_filters
        )
        now = timezone.now()
        cohort = Cohort.objects.create(
            team=self.team,
            name="static in retry backoff",
            is_calculating=True,
            is_static=True,
            last_error_at=now - error_age,
            **source_fields,
        )
        Cohort.objects.filter(pk=cohort.pk).update(created_at=now - relativedelta(hours=2))

        reset_stuck_cohorts()

        cohort.refresh_from_db()
        self.assertEqual(cohort.is_calculating, not expect_reset)
        self.assertEqual(cohort.errors_calculating, 1 if expect_reset else 0)
        self.assertEqual(mock_population_task.delay.called, expect_reset)

    @parameterized.expand(
        [
            # The previous calculation finished two days ago, which says nothing about the current run.
            ("replace_claimed_just_now", CohortPopulationMode.REPLACE, relativedelta(seconds=30), None, False, False),
            ("append_claimed_just_now", CohortPopulationMode.APPEND, relativedelta(seconds=30), None, False, False),
            # A claim from before the request time was recorded, whose attempt is running.
            (
                "attempt_running_for_90_minutes",
                CohortPopulationMode.REPLACE,
                None,
                relativedelta(minutes=90),
                False,
                False,
            ),
            (
                "attempt_recently_finished_without_claim",
                CohortPopulationMode.REPLACE,
                None,
                relativedelta(minutes=30),
                True,
                True,
            ),
            (
                "attempt_killed_past_the_soft_limit",
                CohortPopulationMode.REPLACE,
                relativedelta(hours=6),
                relativedelta(hours=5),
                False,
                True,
            ),
        ]
    )
    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_query")
    def test_reset_stuck_static_cohorts_leaves_a_live_population_alone(
        self,
        _name: str,
        mode: str,
        claim_age: relativedelta | None,
        attempt_age: relativedelta | None,
        attempt_finished: bool,
        expect_reset: bool,
        mock_insert_cohort_from_query: MagicMock,
    ) -> None:
        now = timezone.now()
        claimed_at = now - claim_age if claim_age else None
        cohort = Cohort.objects.create(
            team=self.team,
            name="static repopulating",
            is_calculating=True,
            is_static=True,
            query={"kind": "HogQLQuery", "query": "SELECT id FROM persons"},
            last_calculation=now - relativedelta(days=2),
            pending_population_mode=mode,
            population_claimed_at=claimed_at,
        )
        if attempt_age is not None:
            CohortCalculationHistory.objects.create(
                team=self.team,
                cohort=cohort,
                filters={},
                started_at=now - attempt_age,
                finished_at=now - relativedelta(minutes=10) if attempt_finished else None,
            )

        reset_stuck_cohorts()

        cohort.refresh_from_db()
        self.assertEqual(cohort.is_calculating, not expect_reset)
        self.assertEqual(mock_insert_cohort_from_query.delay.called, expect_reset)
        # A redispatch serves the same request, so it keeps the mode and the request time.
        self.assertEqual((cohort.pending_population_mode, cohort.population_claimed_at), (mode, claimed_at))

    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_query")
    def test_reset_stuck_static_cohorts_checks_newest_history_row(
        self, mock_insert_cohort_from_query: MagicMock
    ) -> None:
        now = timezone.now()
        claimed_at = now - relativedelta(hours=6)
        cohort = Cohort.objects.create(
            team=self.team,
            name="static with old and new open history",
            is_calculating=True,
            is_static=True,
            query={"kind": "HogQLQuery", "query": "SELECT id FROM persons"},
            last_calculation=now - relativedelta(days=2),
            pending_population_mode=CohortPopulationMode.REPLACE,
            population_claimed_at=claimed_at,
        )
        CohortCalculationHistory.objects.create(
            team=self.team,
            cohort=cohort,
            filters={},
            started_at=now - relativedelta(hours=5),
            finished_at=None,
        )
        CohortCalculationHistory.objects.create(
            team=self.team,
            cohort=cohort,
            filters={},
            started_at=now - relativedelta(minutes=10),
            finished_at=None,
        )

        reset_stuck_cohorts()

        cohort.refresh_from_db()
        self.assertTrue(cohort.is_calculating)
        mock_insert_cohort_from_query.delay.assert_not_called()

    @parameterized.expand([("released", False, True), ("claimed_again", True, False)])
    def test_ending_a_pending_population_leaves_a_cohort_claimed_again(
        self, _name: str, is_calculating: bool, expect_cleared: bool
    ) -> None:
        # A request can claim the cohort between the sweep's reset and this clear. Its fields belong to it, so a
        # replace it claimed must keep its mode, or it would run as an append.
        marker = timezone.now().replace(microsecond=0)
        cohort = Cohort.objects.create(
            team=self.team,
            name="static cohort",
            is_static=True,
            is_calculating=is_calculating,
            pending_population_mode=CohortPopulationMode.REPLACE,
            population_marker=marker,
            population_claimed_at=marker,
        )

        _end_pending_population(cohort.pk)

        cohort.refresh_from_db()
        expected = (None, None, None) if expect_cleared else (CohortPopulationMode.REPLACE, marker, marker)
        self.assertEqual(
            (cohort.pending_population_mode, cohort.population_marker, cohort.population_claimed_at), expected
        )

    @parameterized.expand(
        [
            ("flag_run_killed", None, relativedelta(hours=6), [], None, 0, True),
            ("flag_run_within_soft_limit", None, relativedelta(hours=4), [], None, 0, False),
            (
                "filters_without_values_killed",
                {"properties": {"type": "AND"}},
                relativedelta(hours=6),
                [],
                None,
                0,
                True,
            ),
            (
                "csv_reupload_killed",
                {"properties": {}},
                relativedelta(days=3),
                [(relativedelta(hours=6), False)],
                None,
                0,
                True,
            ),
            (
                "csv_reupload_running",
                {"properties": {}},
                relativedelta(days=3),
                [(relativedelta(minutes=10), False)],
                None,
                0,
                False,
            ),
            (
                "csv_reupload_queued_after_a_finished_attempt",
                {"properties": {}},
                relativedelta(days=3),
                [(relativedelta(days=2), True)],
                None,
                0,
                False,
            ),
            (
                "csv_reupload_running_after_a_killed_attempt",
                {"properties": {}},
                relativedelta(days=3),
                [(relativedelta(hours=6), False), (relativedelta(minutes=10), False)],
                None,
                0,
                False,
            ),
            (
                "csv_reupload_queued_to_a_populated_cohort",
                {"properties": {}},
                relativedelta(days=3),
                [],
                relativedelta(days=2),
                0,
                False,
            ),
            ("csv_reupload_queued_to_a_failed_cohort", {"properties": {}}, relativedelta(days=3), [], None, 1, False),
        ]
    )
    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_filters")
    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_query")
    def test_reset_stuck_sourceless_static_cohorts(
        self,
        _name: str,
        filters: dict | None,
        created_age: relativedelta,
        attempts: list[tuple[relativedelta, bool]],
        last_calculation_age: relativedelta | None,
        errors_calculating: int,
        expect_reset: bool,
        mock_insert_cohort_from_query: MagicMock,
        mock_insert_cohort_from_filters: MagicMock,
    ) -> None:
        now = timezone.now()
        marker = now.replace(microsecond=0) - relativedelta(days=4)
        cohort = Cohort.objects.create(
            team=self.team,
            name="static without a population source",
            is_calculating=True,
            is_static=True,
            filters=filters,
            last_calculation=now - last_calculation_age if last_calculation_age else None,
            errors_calculating=errors_calculating,
            # Run fields a replace could have left, which only a reset clears.
            pending_population_mode=CohortPopulationMode.REPLACE,
            population_marker=marker,
            population_claimed_at=marker,
        )
        Cohort.objects.filter(pk=cohort.pk).update(created_at=now - created_age)
        for attempt_age, attempt_finished in attempts:
            CohortCalculationHistory.objects.create(
                team=self.team,
                cohort=cohort,
                filters={},
                started_at=now - attempt_age,
                finished_at=now - attempt_age if attempt_finished else None,
            )

        reset_stuck_cohorts()

        cohort.refresh_from_db()
        self.assertEqual(cohort.is_calculating, not expect_reset)
        self.assertEqual(cohort.errors_calculating, errors_calculating + (1 if expect_reset else 0))
        self.assertEqual(
            (cohort.pending_population_mode, cohort.population_marker, cohort.population_claimed_at),
            (None, None, None) if expect_reset else (CohortPopulationMode.REPLACE, marker, marker),
        )
        mock_insert_cohort_from_query.delay.assert_not_called()
        mock_insert_cohort_from_filters.delay.assert_not_called()
        history = [
            (row.error_code, row.error, row.finished_at is not None)
            for row in CohortCalculationHistory.objects.filter(cohort=cohort).order_by("started_at")
        ]
        expected_history: list[tuple[CohortErrorCode | None, str | None, bool]]
        if expect_reset:
            interrupted = get_friendly_error_message(CohortErrorCode.INTERRUPTED, will_retry=False)
            expected_history = [(CohortErrorCode.INTERRUPTED, interrupted, True)]
        else:
            expected_history = [(None, None, attempt_finished) for _, attempt_finished in attempts]
        self.assertEqual(history, expected_history)

    @parameterized.expand(
        [
            ("query", insert_cohort_from_query, QUERY_CH_INSERT_PATH),
            ("filters", insert_cohort_from_filters, FILTERS_CH_INSERT_PATH),
        ]
    )
    def test_static_population_records_failure_when_retry_cannot_be_published(
        self, _name: str, task: Task, ch_insert_path: str
    ) -> None:
        cohort = Cohort.objects.create(team=self.team, name="static cohort", is_static=True)
        task.push_request(retries=0, called_directly=False, is_eager=True)
        try:
            with (
                patch(ch_insert_path),
                patch(PG_SYNC_PATH, side_effect=_rpc_error(grpc.StatusCode.UNAVAILABLE)),
                patch.object(task, "retry", side_effect=Reject("broker unavailable", requeue=False)),
                self.assertRaises(Reject),
            ):
                task.run(cohort.id, self.team.pk)
        finally:
            task.pop_request()

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)

    @parameterized.expand(
        [
            ("query", insert_cohort_from_query, QUERY_CH_INSERT_PATH),
            ("filters", insert_cohort_from_filters, FILTERS_CH_INSERT_PATH),
        ]
    )
    def test_static_population_records_failure_when_the_worker_cuts_the_run_short(
        self, _name: str, task: Task, ch_insert_path: str
    ) -> None:
        # A shutdown leaves the cohort half-written, so it must not be finalized as calculated.
        cohort = Cohort.objects.create(team=self.team, name="static cohort", is_static=True)

        with patch(ch_insert_path, side_effect=SystemExit("worker shutdown")), self.assertRaises(SystemExit):
            task(cohort.id, self.team.pk)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)
        self.assertIsNone(cohort.last_calculation)

    def test_insert_cohort_from_filters_count_updated_on_exception(self) -> None:
        cohort = Cohort.objects.create(
            team_id=self.team.pk,
            name="test_filters_cohort",
            is_static=True,
            count=0,
            filters=PERSON_EMAIL_FILTERS,
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
            (
                "clickhouse_retries_exhausted",
                "products.cohorts.backend.models.util.insert_static_cohort",
                ClickHouseAtCapacity,
                calculate_cohort_from_list.max_retries,
                False,
            ),
            (
                "clickhouse_called_directly",
                "products.cohorts.backend.models.util.insert_static_cohort",
                ClickHouseAtCapacity,
                0,
                True,
            ),
            (
                "not_retryable",
                "products.cohorts.backend.models.util.insert_static_cohort",
                ValueError,
                0,
                False,
            ),
            (
                "personhog_retries_exhausted",
                "products.cohorts.backend.models.util.insert_cohort_members",
                lambda: _rpc_error(grpc.StatusCode.UNAVAILABLE),
                calculate_cohort_from_list.max_retries,
                False,
            ),
            (
                "personhog_not_retryable",
                "products.cohorts.backend.models.util.insert_cohort_members",
                lambda: _rpc_error(grpc.StatusCode.INVALID_ARGUMENT),
                0,
                False,
            ),
        ]
    )
    def test_records_failure_when_nothing_will_retry(
        self,
        _name: str,
        insert_path: str,
        error_factory: Callable[[], Exception],
        retries: int,
        called_directly: bool,
    ) -> None:
        error = error_factory()
        create_person(team=self.team, distinct_ids=["user123"])
        cohort = self._create_static_cohort()

        with patch(insert_path, side_effect=error), self.assertRaises(type(error)):
            self._run_task(cohort, retries=retries, called_directly=called_directly)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)
        self.assertIsNotNone(cohort.last_error_at)

    @parameterized.expand(
        [
            (
                "clickhouse",
                "products.cohorts.backend.models.util.insert_static_cohort",
                ClickHouseAtCapacity,
            ),
            (
                "personhog",
                "products.cohorts.backend.models.util.insert_cohort_members",
                lambda: _rpc_error(grpc.StatusCode.UNAVAILABLE),
            ),
            (
                "postgres_on_first_read",
                COHORT_READ_PATH,
                lambda: OperationalError("server closed the connection unexpectedly"),
            ),
        ]
    )
    def test_leaves_state_untouched_while_retries_remain(
        self, _name: str, insert_path: str, error_factory: Callable[[], Exception]
    ) -> None:
        create_person(team=self.team, distinct_ids=["user123"])
        cohort = self._create_static_cohort()

        with patch(insert_path, side_effect=error_factory()), self.assertRaises(Retry):
            self._run_task(cohort, retries=0, called_directly=False)

        cohort.refresh_from_db()
        self.assertTrue(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertIsNotNone(cohort.last_error_at)

    def test_skips_a_cohort_flipped_to_dynamic(self) -> None:
        create_person(team=self.team, distinct_ids=["user123"])
        cohort = self._create_static_cohort()
        Cohort.objects.filter(pk=cohort.pk).update(is_static=False)

        with patch("products.cohorts.backend.models.util.insert_static_cohort") as mock_insert_ch:
            self._run_task(cohort, retries=0, called_directly=False)

        mock_insert_ch.assert_not_called()
        cohort.refresh_from_db()
        self.assertTrue(cohort.is_calculating)
        self.assertEqual(count_cohort_members(cohort.team_id, cohort.pk), 0)

    def test_records_failure_when_the_worker_cuts_the_run_short(self) -> None:
        create_person(team=self.team, distinct_ids=["user123"])
        cohort = self._create_static_cohort()

        with (
            patch("products.cohorts.backend.models.util.insert_static_cohort", side_effect=SystemExit("shutdown")),
            self.assertRaises(SystemExit),
        ):
            self._run_task(cohort, retries=0, called_directly=False)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)

    def test_records_failure_when_retry_cannot_be_published(self) -> None:
        create_person(team=self.team, distinct_ids=["user123"])
        cohort = self._create_static_cohort()

        with (
            patch("products.cohorts.backend.models.util.insert_static_cohort", side_effect=ClickHouseAtCapacity()),
            patch.object(calculate_cohort_from_list, "retry", side_effect=Reject("broker unavailable", requeue=False)),
            self.assertRaises(Reject),
        ):
            self._run_task(cohort, retries=0, called_directly=False)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)

    @parameterized.expand(
        [
            (
                "clickhouse",
                "products.cohorts.backend.models.util.insert_static_cohort",
                ClickHouseAtCapacity,
            ),
            (
                "personhog",
                "products.cohorts.backend.models.util.insert_cohort_members",
                lambda: _rpc_error(grpc.StatusCode.UNAVAILABLE),
            ),
        ]
    )
    def test_retry_after_transient_failure_completes_the_cohort(
        self, _name: str, insert_path: str, error_factory: Callable[[], Exception]
    ) -> None:
        create_person(team=self.team, distinct_ids=["user123"])
        cohort = self._create_static_cohort()

        with patch(insert_path, side_effect=error_factory()), self.assertRaises(Retry):
            self._run_task(cohort, retries=0, called_directly=False)

        self._run_task(cohort, retries=1, called_directly=False)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertEqual(count_cohort_members(cohort.team_id, cohort.pk), 1)


class TestCollectCohortQueryStats(APIBaseTest):
    @parameterized.expand(
        [
            ("retries_remain", 0, Retry),
            ("retries_exhausted", 3, None),
        ]
    )
    def test_missing_stats_are_not_logged_as_a_failure(
        self, _name: str, retries: int, expected_exception: type[Exception] | None
    ) -> None:
        cohort = Cohort.objects.create(team=self.team, name="cohort")
        history = CohortCalculationHistory.objects.create(
            team=self.team, cohort=cohort, filters={}, started_at=timezone.now()
        )
        task = collect_cohort_query_stats
        task.push_request(retries=retries, called_directly=False, is_eager=True)
        try:
            with (
                patch("posthog.tasks.calculate_cohort.get_clickhouse_query_stats", return_value=None),
                patch("posthog.tasks.calculate_cohort.logger") as mock_logger,
                self.assertRaises(expected_exception) if expected_exception else nullcontext(),
            ):
                task.run("cohort_calc:abc", cohort.pk, timezone.now().isoformat(), str(history.id), "SELECT 1")
        finally:
            task.pop_request()

        mock_logger.exception.assert_not_called()


class TestScheduleStaticCohortCountRefresh(SimpleTestCase):
    def test_a_failed_publish_lets_the_next_insert_schedule_the_recount(self) -> None:
        cohort_id = 987654
        self.addCleanup(cache.delete, f"static-cohort-count-refresh:{cohort_id}")

        with patch.object(
            refresh_static_cohort_count, "apply_async", side_effect=[ConnectionError("broker down"), None]
        ) as publish:
            with self.assertRaises(ConnectionError):
                schedule_static_cohort_count_refresh(team_id=1, cohort_id=cohort_id)
            schedule_static_cohort_count_refresh(team_id=1, cohort_id=cohort_id)

        assert publish.call_count == 2
