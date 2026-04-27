"""Tests for the weekly batched dmat backfill activities (PENDING flow)."""

import re

import pytest
from unittest.mock import patch

from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.temporal.backfill_materialized_property.activities import (
    ActivateSlotsInputs,
    AssignPendingSlotsInputs,
    FailSlotsInputs,
    RunBatchedMutationInputs,
    _build_batched_update_command,
    _ColumnAssignment,
    _plan_column_assignments,
    activate_slots,
    assign_pending_slots,
    fail_slots,
    run_batched_mutation,
)

from products.event_definitions.backend.models.property_definition import PropertyType


def _make_pending_slot(team, name: str) -> MaterializedColumnSlot:
    prop_def = PropertyDefinition.objects.create(
        team=team,
        name=name,
        property_type=PropertyType.String,
        type=PropertyDefinition.Type.EVENT,
    )
    return MaterializedColumnSlot.objects.create(
        team=team,
        property_definition=prop_def,
        property_type=PropertyType.String,
        slot_index=None,
        state=MaterializedColumnSlotState.PENDING,
    )


@pytest.mark.django_db(transaction=True)
class TestPlanColumnAssignments:
    def test_packs_two_teams_into_a_single_column(self, team, organization):
        from posthog.models import Team

        team_a = team
        team_b = Team.objects.create(organization=organization, name="Team B")
        slot_a = _make_pending_slot(team_a, "browser")
        slot_b = _make_pending_slot(team_b, "plan")

        plan = _plan_column_assignments([slot_a, slot_b], used_indexes_by_team={})

        assert len(plan) == 1
        assert plan[0].column_index == 0
        team_ids = {t for (t, _, _) in plan[0].branches}
        assert team_ids == {team_a.id, team_b.id}

    def test_same_team_with_two_pending_uses_two_columns(self, team):
        slot_one = _make_pending_slot(team, "browser")
        slot_two = _make_pending_slot(team, "utm_source")

        plan = _plan_column_assignments([slot_one, slot_two], used_indexes_by_team={})

        assert {a.column_index for a in plan} == {0, 1}
        # Each column has exactly one branch for this team.
        for assignment in plan:
            assert len(assignment.branches) == 1
            assert assignment.branches[0][0] == team.id

    def test_skips_columns_already_used_by_team(self, team):
        slot = _make_pending_slot(team, "browser")

        plan = _plan_column_assignments(
            [slot],
            used_indexes_by_team={team.id: {0, 1, 2}},
        )

        assert len(plan) == 1
        assert plan[0].column_index == 3

    def test_assignment_is_deterministic_across_calls(self, team, organization):
        from posthog.models import Team

        team_b = Team.objects.create(organization=organization, name="Team B")
        slots = [
            _make_pending_slot(team_b, "z_prop"),
            _make_pending_slot(team, "a_prop"),
            _make_pending_slot(team, "b_prop"),
        ]

        plan1 = _plan_column_assignments(slots, used_indexes_by_team={})
        plan2 = _plan_column_assignments(slots, used_indexes_by_team={})

        assert [(a.column_index, sorted(a.branches)) for a in plan1] == [
            (a.column_index, sorted(a.branches)) for a in plan2
        ]


class TestBuildBatchedUpdateCommand:
    def test_emits_one_set_clause_per_column_with_multif_branches(self):
        assignments = [
            _ColumnAssignment(
                column_index=12,
                branches=[
                    (2, "browser", "11111111-1111-1111-1111-111111111111"),
                    (47, "plan_name", "22222222-2222-2222-2222-222222222222"),
                ],
            ),
            _ColumnAssignment(
                column_index=13,
                branches=[(2, "utm_source", "33333333-3333-3333-3333-333333333333")],
            ),
        ]
        command, params = _build_batched_update_command(assignments)

        # SET clause shape — one per column, with multiIf and a default branch keeping the existing value.
        assert "dmat_string_12 = multiIf(" in command
        assert "dmat_string_13 = multiIf(" in command
        # Default branch trailing the multiIf is the column itself.
        assert "dmat_string_12)" in command
        assert "dmat_string_13)" in command
        # All affected teams collected into the WHERE clause.
        assert re.search(r"WHERE team_id IN \(2, 47\)$", command), command

    def test_property_names_are_parameterised_not_inlined(self):
        slot_id = "11111111-1111-1111-1111-111111111111"
        injection = "haha'; DROP TABLE events; --"
        assignment = _ColumnAssignment(column_index=5, branches=[(7, injection, slot_id)])

        command, params = _build_batched_update_command([assignment])

        assert injection not in command, "property name must be parameterised, not inlined"
        # Param key is derived from the slot UUID so collisions across the mutation are impossible.
        param_key = f"prop_{slot_id.replace('-', '')}"
        assert params[param_key] == injection
        assert f"%({param_key})s" in command

    def test_empty_assignments_raise(self):
        with pytest.raises(ValueError, match="no assignments"):
            _build_batched_update_command([])


@pytest.mark.django_db(transaction=True)
class TestAssignPendingSlots:
    def test_transitions_pending_slots_to_backfill_with_indexes(self, team, activity_environment):
        slot_a = _make_pending_slot(team, "browser")
        slot_b = _make_pending_slot(team, "utm_source")

        result = activity_environment.run(
            assign_pending_slots,
            AssignPendingSlotsInputs(workflow_id="wf-test"),
        )

        assert sorted(result.assigned_slot_ids) == sorted([str(slot_a.id), str(slot_b.id)])
        slot_a.refresh_from_db()
        slot_b.refresh_from_db()
        assert slot_a.state == MaterializedColumnSlotState.BACKFILL
        assert slot_b.state == MaterializedColumnSlotState.BACKFILL
        assert slot_a.slot_index is not None
        assert slot_b.slot_index is not None
        assert slot_a.slot_index != slot_b.slot_index
        assert slot_a.backfill_temporal_workflow_id == "wf-test"

    def test_no_pending_slots_returns_empty_plan(self, team, activity_environment):
        result = activity_environment.run(
            assign_pending_slots,
            AssignPendingSlotsInputs(workflow_id="wf-test"),
        )

        assert result.assigned_slot_ids == []
        assert result.assignments == []

    def test_avoids_collisions_with_existing_ready_slot_indexes(self, team, activity_environment):
        # Pre-existing READY slot at index 0 means the new pending slot must land elsewhere.
        existing_prop = PropertyDefinition.objects.create(
            team=team,
            name="existing",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=existing_prop,
            property_type=PropertyType.String,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
        )

        new_slot = _make_pending_slot(team, "new_prop")

        activity_environment.run(
            assign_pending_slots,
            AssignPendingSlotsInputs(workflow_id="wf-test"),
        )

        new_slot.refresh_from_db()
        assert new_slot.slot_index == 1


@pytest.mark.django_db(transaction=True)
class TestActivateAndFailSlots:
    def test_activate_slots_transitions_backfill_to_ready(self, team, activity_environment):
        prop = PropertyDefinition.objects.create(
            team=team,
            name="p",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop,
            property_type=PropertyType.String,
            slot_index=3,
            state=MaterializedColumnSlotState.BACKFILL,
        )

        activated = activity_environment.run(activate_slots, ActivateSlotsInputs(slot_ids=[str(slot.id)]))

        assert activated == 1
        slot.refresh_from_db()
        assert slot.state == MaterializedColumnSlotState.READY

    def test_activate_slots_skips_non_backfill_slots(self, team, activity_environment):
        prop = PropertyDefinition.objects.create(
            team=team,
            name="p",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        # ERROR slot should not be transitioned to READY by activate_slots.
        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop,
            property_type=PropertyType.String,
            slot_index=3,
            state=MaterializedColumnSlotState.ERROR,
        )

        activated = activity_environment.run(activate_slots, ActivateSlotsInputs(slot_ids=[str(slot.id)]))

        assert activated == 0
        slot.refresh_from_db()
        assert slot.state == MaterializedColumnSlotState.ERROR

    def test_fail_slots_records_error_message(self, team, activity_environment):
        prop = PropertyDefinition.objects.create(
            team=team,
            name="p",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop,
            property_type=PropertyType.String,
            slot_index=4,
            state=MaterializedColumnSlotState.BACKFILL,
        )

        failed = activity_environment.run(
            fail_slots,
            FailSlotsInputs(slot_ids=[str(slot.id)], error_message="ClickHouse OOM"),
        )

        assert failed == 1
        slot.refresh_from_db()
        assert slot.state == MaterializedColumnSlotState.ERROR
        assert slot.error_message == "ClickHouse OOM"


@pytest.mark.django_db(transaction=True)
class TestRunBatchedMutation:
    @patch("posthog.temporal.backfill_materialized_property.activities.AlterTableMutationRunner")
    @patch("posthog.temporal.backfill_materialized_property.activities.get_cluster")
    def test_no_op_when_no_assignments(self, mock_get_cluster, mock_runner_cls, activity_environment):
        activity_environment.run(run_batched_mutation, RunBatchedMutationInputs(assignments=[]))
        mock_get_cluster.assert_not_called()
        mock_runner_cls.assert_not_called()

    @patch("posthog.temporal.backfill_materialized_property.activities.AlterTableMutationRunner")
    @patch("posthog.temporal.backfill_materialized_property.activities.get_cluster")
    def test_invokes_alter_table_runner_with_built_command(
        self, mock_get_cluster, mock_runner_cls, activity_environment
    ):
        assignments = [
            _ColumnAssignment(
                column_index=7,
                branches=[(2, "browser", "11111111-1111-1111-1111-111111111111")],
            )
        ]
        runner_instance = mock_runner_cls.return_value

        activity_environment.run(run_batched_mutation, RunBatchedMutationInputs(assignments=assignments))

        mock_runner_cls.assert_called_once()
        call_kwargs = mock_runner_cls.call_args.kwargs
        assert call_kwargs["table"] == "sharded_events"
        # Single command with the multiIf body assembled from the assignment.
        commands = call_kwargs["commands"]
        assert len(commands) == 1
        (command,) = commands
        assert "dmat_string_7 = multiIf(team_id = 2," in command
        assert "WHERE team_id IN (2)" in command
        # Property name lives in params, not the SQL.
        assert "browser" not in command
        assert "browser" in call_kwargs["parameters"].values()

        runner_instance.run_on_shards.assert_called_once_with(mock_get_cluster.return_value)
