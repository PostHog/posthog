from io import StringIO

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError, OutputWrapper

from parameterized import parameterized
from temporalio.common import WorkflowIDReusePolicy

from posthog.management.commands.backfill_precalculated_events import (
    MAX_BACKFILL_DAYS,
    Command,
    compute_backfill_days,
    extract_behavioral_filters,
)
from posthog.models import Cohort, Team
from posthog.models.cohort.cohort import CohortType
from posthog.temporal.messaging.backfill_precalculated_events_coordinator_workflow import (
    BackfillPrecalculatedEventsCoordinatorInputs,
)
from posthog.temporal.messaging.types import BehavioralEventFilter


class TestExtractBehavioralFilters(BaseTest):
    def test_extracts_performed_event_filter(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Pageview Users",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": "30",
                            "time_interval": "day",
                            "conditionHash": "abc123",
                            "bytecode": ["_H", 1, "op1", "op2"],
                        }
                    ],
                }
            },
        )

        filters = extract_behavioral_filters(cohort)

        assert len(filters) == 1
        assert filters[0].condition_hash == "abc123"
        assert filters[0].event_name == "$pageview"
        assert filters[0].time_value == 30
        assert filters[0].time_interval == "day"
        assert filters[0].bytecode == ["_H", 1, "op1", "op2"]

    def test_extracts_performed_event_multiple_filter(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Frequent Users",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "purchase",
                            "value": "performed_event_multiple",
                            "event_type": "events",
                            "time_value": "7",
                            "time_interval": "week",
                            "operator": "gte",
                            "operator_value": 3,
                            "conditionHash": "def456",
                            "bytecode": ["_H", 1, "op3", "op4"],
                        }
                    ],
                }
            },
        )

        filters = extract_behavioral_filters(cohort)

        assert len(filters) == 1
        assert filters[0].condition_hash == "def456"
        assert filters[0].event_name == "purchase"
        assert filters[0].time_value == 7
        assert filters[0].time_interval == "week"

    def test_skips_unsupported_behavioral_types(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="First Time Users",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event_first_time",
                            "event_type": "events",
                            "time_value": "30",
                            "time_interval": "day",
                            "conditionHash": "abc123",
                            "bytecode": ["_H", 1, "op1"],
                        },
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event_sequence",
                            "event_type": "events",
                            "conditionHash": "def456",
                            "bytecode": ["_H", 1, "op2"],
                        },
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "stopped_performing_event",
                            "event_type": "events",
                            "conditionHash": "ghi789",
                            "bytecode": ["_H", 1, "op3"],
                        },
                    ],
                }
            },
        )

        filters = extract_behavioral_filters(cohort)
        assert len(filters) == 0

    def test_skips_person_property_filters(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Mixed Filters",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "email",
                            "value": "test@example.com",
                            "operator": "exact",
                            "conditionHash": "person_hash",
                            "bytecode": ["_H", 1, "person_op"],
                        },
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": "30",
                            "time_interval": "day",
                            "conditionHash": "event_hash",
                            "bytecode": ["_H", 1, "event_op"],
                        },
                    ],
                }
            },
        )

        filters = extract_behavioral_filters(cohort)

        assert len(filters) == 1
        assert filters[0].condition_hash == "event_hash"

    def test_skips_filters_missing_required_fields(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Incomplete Filters",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            # Missing conditionHash
                            "bytecode": ["_H", 1, "op1"],
                        },
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            "conditionHash": "hash1",
                            # Missing bytecode
                        },
                    ],
                }
            },
        )

        filters = extract_behavioral_filters(cohort)
        assert len(filters) == 0

    def test_skips_action_id_filters(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Action Cohort",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": 42,  # Action ID (int, not str)
                            "value": "performed_event",
                            "event_type": "actions",
                            "time_value": "30",
                            "time_interval": "day",
                            "conditionHash": "action_hash",
                            "bytecode": ["_H", 1, "op1"],
                        }
                    ],
                }
            },
        )

        filters = extract_behavioral_filters(cohort)
        assert len(filters) == 0

    def test_traverses_nested_groups(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Nested Groups",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "behavioral",
                                    "key": "$pageview",
                                    "value": "performed_event",
                                    "event_type": "events",
                                    "time_value": "30",
                                    "time_interval": "day",
                                    "conditionHash": "hash1",
                                    "bytecode": ["_H", 1, "op1"],
                                }
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "behavioral",
                                    "key": "purchase",
                                    "value": "performed_event",
                                    "event_type": "events",
                                    "time_value": "7",
                                    "time_interval": "day",
                                    "conditionHash": "hash2",
                                    "bytecode": ["_H", 1, "op2"],
                                }
                            ],
                        },
                    ],
                }
            },
        )

        filters = extract_behavioral_filters(cohort)

        assert len(filters) == 2
        hashes = {f.condition_hash for f in filters}
        assert hashes == {"hash1", "hash2"}

    def test_defaults_time_window_when_missing(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="No Time Window",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            # No time_value or time_interval
                            "conditionHash": "hash1",
                            "bytecode": ["_H", 1, "op1"],
                        }
                    ],
                }
            },
        )

        filters = extract_behavioral_filters(cohort)

        assert len(filters) == 1
        assert filters[0].time_value == 30
        assert filters[0].time_interval == "day"

    def test_captures_event_filters(self):
        event_filters = [
            {"type": "event", "key": "url", "value": "/pricing", "operator": "exact"},
        ]
        cohort = Cohort.objects.create(
            team=self.team,
            name="Filtered Events",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": "30",
                            "time_interval": "day",
                            "conditionHash": "hash1",
                            "bytecode": ["_H", 1, "op1"],
                            "event_filters": event_filters,
                        }
                    ],
                }
            },
        )

        filters = extract_behavioral_filters(cohort)

        assert len(filters) == 1
        assert filters[0].event_filters == event_filters

    def test_empty_cohort_filters(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Empty",
            cohort_type=CohortType.REALTIME,
            filters={},
        )

        filters = extract_behavioral_filters(cohort)
        assert len(filters) == 0

    def test_null_cohort_filters(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Null",
            cohort_type=CohortType.REALTIME,
            filters=None,
        )

        filters = extract_behavioral_filters(cohort)
        assert len(filters) == 0


class TestComputeBackfillDays(BaseTest):
    @staticmethod
    def _make_filter(time_value: int, time_interval: str) -> BehavioralEventFilter:
        return BehavioralEventFilter(
            condition_hash="test",
            bytecode=["_H", 1, "op"],
            cohort_ids=[1],
            event_name="$pageview",
            time_value=time_value,
            time_interval=time_interval,
        )

    @parameterized.expand(
        [
            ("day_30", [(30, "day")], 30, 30),
            ("week_4", [(4, "week")], 28, 28),
            ("month_3_clamped", [(3, "month")], MAX_BACKFILL_DAYS, 90),
            ("takes_max", [(7, "day"), (30, "day"), (14, "day")], 30, 30),
            ("clamps_to_max", [(365, "day")], MAX_BACKFILL_DAYS, 365),
            ("unknown_interval_uses_1x", [(10, "unknown")], 10, 10),
        ]
    )
    def test_compute_backfill_days(self, _name, filter_inputs, expected_clamped, expected_unclamped):
        filters = [self._make_filter(tv, ti) for tv, ti in filter_inputs]
        clamped, unclamped = compute_backfill_days(filters)
        assert clamped == expected_clamped
        assert unclamped == expected_unclamped

    def test_empty_filters_returns_zero(self):
        assert compute_backfill_days([]) == (0, 0)


class TestBackfillPrecalculatedEventsCommand(BaseTest):
    def setUp(self):
        super().setUp()
        self.command_output = StringIO()

    def test_cross_cohort_deduplication(self):
        shared_hash = "shared_event_hash"
        shared_bytecode = ["_H", 1, "op1"]

        cohort1 = Cohort.objects.create(
            team=self.team,
            name="Cohort A",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": "30",
                            "time_interval": "day",
                            "conditionHash": shared_hash,
                            "bytecode": shared_bytecode,
                        }
                    ],
                }
            },
        )

        cohort2 = Cohort.objects.create(
            team=self.team,
            name="Cohort B",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": "30",
                            "time_interval": "day",
                            "conditionHash": shared_hash,
                            "bytecode": shared_bytecode,
                        }
                    ],
                }
            },
        )

        with patch(
            "posthog.management.commands.backfill_precalculated_events.Command.run_temporal_workflow"
        ) as mock_workflow:
            mock_workflow.return_value = "test-workflow-id"
            call_command("backfill_precalculated_events", "--team-id", str(self.team.id), stdout=self.command_output)

        self.assertTrue(mock_workflow.called)
        call_args = mock_workflow.call_args[1]
        filters = call_args["filters"]
        cohort_ids = call_args["cohort_ids"]

        self.assertEqual(len(filters), 1)
        self.assertEqual(set(cohort_ids), {cohort1.id, cohort2.id})
        self.assertEqual(filters[0].condition_hash, shared_hash)
        self.assertEqual(set(filters[0].cohort_ids), {cohort1.id, cohort2.id})

    def test_skips_cohorts_without_behavioral_filters(self):
        good_cohort = Cohort.objects.create(
            team=self.team,
            name="Behavioral Cohort",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": "30",
                            "time_interval": "day",
                            "conditionHash": "hash1",
                            "bytecode": ["_H", 1, "op1"],
                        }
                    ],
                }
            },
        )

        person_only_cohort = Cohort.objects.create(
            team=self.team,
            name="Person Property Only",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "email",
                            "value": "test@example.com",
                            "operator": "exact",
                            "conditionHash": "person_hash",
                            "bytecode": ["_H", 1, "person_op"],
                        }
                    ],
                }
            },
        )

        with patch(
            "posthog.management.commands.backfill_precalculated_events.Command.run_temporal_workflow"
        ) as mock_workflow:
            mock_workflow.return_value = "test-workflow-id"
            call_command("backfill_precalculated_events", "--team-id", str(self.team.id), stdout=self.command_output)

        call_args = mock_workflow.call_args[1]
        cohort_ids = call_args["cohort_ids"]

        self.assertEqual(cohort_ids, [good_cohort.id])

        output = self.command_output.getvalue()
        self.assertIn(f"Skipping cohort {person_only_cohort.id}", output)

    def test_days_override_clamped_to_max(self):
        Cohort.objects.create(
            team=self.team,
            name="Test Cohort",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": "30",
                            "time_interval": "day",
                            "conditionHash": "hash1",
                            "bytecode": ["_H", 1, "op1"],
                        }
                    ],
                }
            },
        )

        with patch(
            "posthog.management.commands.backfill_precalculated_events.Command.run_temporal_workflow"
        ) as mock_workflow:
            mock_workflow.return_value = "test-workflow-id"
            call_command(
                "backfill_precalculated_events",
                "--team-id",
                str(self.team.id),
                "--days",
                "999",
                stdout=self.command_output,
            )

        call_args = mock_workflow.call_args[1]
        self.assertEqual(call_args["effective_days"], MAX_BACKFILL_DAYS)

        output = self.command_output.getvalue()
        self.assertIn("exceeds MAX_BACKFILL_DAYS", output)

    def test_auto_computes_days_from_filters(self):
        Cohort.objects.create(
            team=self.team,
            name="Short Window",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": "7",
                            "time_interval": "day",
                            "conditionHash": "hash1",
                            "bytecode": ["_H", 1, "op1"],
                        }
                    ],
                }
            },
        )

        Cohort.objects.create(
            team=self.team,
            name="Long Window",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "purchase",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": "60",
                            "time_interval": "day",
                            "conditionHash": "hash2",
                            "bytecode": ["_H", 1, "op2"],
                        }
                    ],
                }
            },
        )

        with patch(
            "posthog.management.commands.backfill_precalculated_events.Command.run_temporal_workflow"
        ) as mock_workflow:
            mock_workflow.return_value = "test-workflow-id"
            call_command("backfill_precalculated_events", "--team-id", str(self.team.id), stdout=self.command_output)

        call_args = mock_workflow.call_args[1]
        self.assertEqual(call_args["effective_days"], 60)

    def test_no_realtime_cohorts_shows_warning(self):
        call_command("backfill_precalculated_events", "--team-id", str(self.team.id), stdout=self.command_output)

        output = self.command_output.getvalue()
        self.assertIn("No realtime cohorts found", output)

    def test_validation_rejects_both_team_id_and_team_ids(self):
        with pytest.raises(CommandError, match="Cannot use both"):
            call_command(
                "backfill_precalculated_events",
                "--team-id",
                "1",
                "--team-ids",
                "2",
                "3",
                stdout=self.command_output,
            )

    def test_validation_rejects_negative_days(self):
        with pytest.raises(CommandError, match="--days must be a positive integer"):
            call_command(
                "backfill_precalculated_events",
                "--team-id",
                str(self.team.id),
                "--days",
                "-1",
                stdout=self.command_output,
            )

    def test_team_ids_processes_multiple_teams(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        Cohort.objects.create(
            team=self.team,
            name="Cohort Team 1",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": "30",
                            "time_interval": "day",
                            "conditionHash": "hash_t1",
                            "bytecode": ["_H", 1, "op1"],
                        }
                    ],
                }
            },
        )

        Cohort.objects.create(
            team=team2,
            name="Cohort Team 2",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "purchase",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": "14",
                            "time_interval": "day",
                            "conditionHash": "hash_t2",
                            "bytecode": ["_H", 1, "op2"],
                        }
                    ],
                }
            },
        )

        with patch(
            "posthog.management.commands.backfill_precalculated_events.Command.run_temporal_workflow"
        ) as mock_workflow:
            mock_workflow.return_value = "test-workflow-id"
            call_command(
                "backfill_precalculated_events",
                "--team-ids",
                str(self.team.id),
                str(team2.id),
                stdout=self.command_output,
            )

        self.assertEqual(mock_workflow.call_count, 2)
        team_ids_called = sorted(call[1]["team_id"] for call in mock_workflow.call_args_list)
        self.assertEqual(team_ids_called, sorted([self.team.id, team2.id]))

    def test_cohort_id_restricts_to_specific_cohort(self):
        target_cohort = Cohort.objects.create(
            team=self.team,
            name="Target Cohort",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": "30",
                            "time_interval": "day",
                            "conditionHash": "target_hash",
                            "bytecode": ["_H", 1, "op1"],
                        }
                    ],
                }
            },
        )

        Cohort.objects.create(
            team=self.team,
            name="Other Cohort",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "purchase",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": "7",
                            "time_interval": "day",
                            "conditionHash": "other_hash",
                            "bytecode": ["_H", 1, "op2"],
                        }
                    ],
                }
            },
        )

        with patch(
            "posthog.management.commands.backfill_precalculated_events.Command.run_temporal_workflow"
        ) as mock_workflow:
            mock_workflow.return_value = "test-workflow-id"
            call_command(
                "backfill_precalculated_events",
                "--team-id",
                str(self.team.id),
                "--cohort-id",
                str(target_cohort.id),
                stdout=self.command_output,
            )

        self.assertTrue(mock_workflow.called)
        call_args = mock_workflow.call_args[1]
        filters = call_args["filters"]
        cohort_ids = call_args["cohort_ids"]

        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0].condition_hash, "target_hash")
        self.assertEqual(cohort_ids, [target_cohort.id])


class TestRunTemporalWorkflow(BaseTest):
    def setUp(self):
        super().setUp()
        self.command = Command()
        self.command.stdout = OutputWrapper(StringIO())
        self.filters = [
            BehavioralEventFilter(
                condition_hash="hash_1",
                event_name="$pageview",
                bytecode=["_H", 1, "op"],
                time_value=30,
                time_interval="day",
                cohort_ids=[1, 2],
            ),
            BehavioralEventFilter(
                condition_hash="hash_2",
                event_name="$autocapture",
                bytecode=["_H", 1, "op"],
                time_value=7,
                time_interval="day",
                cohort_ids=[2],
            ),
        ]

    def test_starts_workflow_with_expected_inputs_and_task_queue(self):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()

        with (
            patch(
                "posthog.management.commands.backfill_precalculated_events.async_connect",
                new=AsyncMock(return_value=mock_client),
            ),
            patch(
                "posthog.management.commands.backfill_precalculated_events.store_event_filters",
                return_value="redis-key",
            ) as mock_store,
        ):
            workflow_id = self.command.run_temporal_workflow(
                team_id=self.team.id,
                filters=self.filters,
                cohort_ids=[1, 2],
                effective_days=14,
                concurrent_workflows=5,
                force_reprocess=False,
            )

        mock_store.assert_called_once_with(self.filters, self.team.id)
        mock_client.start_workflow.assert_awaited_once()
        args, kwargs = mock_client.start_workflow.call_args
        self.assertEqual(args[0], "backfill-precalculated-events-coordinator")
        inputs = args[1]
        self.assertIsInstance(inputs, BackfillPrecalculatedEventsCoordinatorInputs)
        self.assertEqual(inputs.team_id, self.team.id)
        self.assertEqual(inputs.filter_storage_key, "redis-key")
        self.assertEqual(inputs.cohort_ids, [1, 2])
        self.assertEqual(inputs.condition_hashes, ["hash_1", "hash_2"])
        self.assertEqual(inputs.days_to_backfill, 14)
        self.assertEqual(inputs.concurrent_workflows, 5)
        self.assertFalse(inputs.force_reprocess)
        self.assertEqual(kwargs["task_queue"], settings.MESSAGING_TASK_QUEUE)
        self.assertEqual(kwargs["id_reuse_policy"], WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY)
        self.assertEqual(kwargs["id"], workflow_id)
        self.assertTrue(workflow_id.startswith(f"backfill-precalculated-events-team-{self.team.id}-"))

    def test_workflow_id_is_unique_across_rapid_invocations(self):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()

        ids: list[str] = []
        with (
            patch(
                "posthog.management.commands.backfill_precalculated_events.async_connect",
                new=AsyncMock(return_value=mock_client),
            ),
            patch(
                "posthog.management.commands.backfill_precalculated_events.store_event_filters",
                return_value="redis-key",
            ),
        ):
            for _ in range(5):
                ids.append(
                    self.command.run_temporal_workflow(
                        team_id=self.team.id,
                        filters=self.filters,
                        cohort_ids=[1, 2],
                        effective_days=14,
                        concurrent_workflows=5,
                    )
                )

        self.assertEqual(len(set(ids)), len(ids))

    def test_raises_when_start_workflow_fails(self):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch(
                "posthog.management.commands.backfill_precalculated_events.async_connect",
                new=AsyncMock(return_value=mock_client),
            ),
            patch(
                "posthog.management.commands.backfill_precalculated_events.store_event_filters",
                return_value="redis-key",
            ),
            pytest.raises(RuntimeError, match="boom"),
        ):
            self.command.run_temporal_workflow(
                team_id=self.team.id,
                filters=self.filters,
                cohort_ids=[1, 2],
                effective_days=14,
                concurrent_workflows=5,
            )
