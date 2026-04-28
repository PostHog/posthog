"""Tests for the weekly batched dmat backfill activities (PENDING flow)."""

import re

import pytest
from unittest.mock import patch

from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.temporal.backfill_materialized_property.activities import (
    MAX_MULTIIF_BRANCHES_PER_MUTATION,
    ActivateSlotsInputs,
    AssignPendingSlotsInputs,
    FailSlotsInputs,
    FinalizeCompactionInputs,
    RunBatchedMutationInputs,
    _build_batched_update_command,
    _chunk_assignments_by_branch_count,
    _ColumnAssignment,
    _plan_column_assignments,
    activate_slots,
    assign_pending_slots,
    fail_slots,
    finalize_compaction,
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
        self,
        mock_get_cluster,
        mock_runner_cls,
        activity_environment,
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

    @patch("posthog.temporal.backfill_materialized_property.activities.AlterTableMutationRunner")
    @patch("posthog.temporal.backfill_materialized_property.activities.get_cluster")
    def test_splits_into_multiple_mutations_when_branches_exceed_cap(
        self,
        mock_get_cluster,
        mock_runner_cls,
        activity_environment,
    ):
        # Build one assignment per column, each with a small branch count, so the total
        # branch count crosses MAX_MULTIIF_BRANCHES_PER_MUTATION and forces chunking.
        branches_per_column = 50
        column_count = (MAX_MULTIIF_BRANCHES_PER_MUTATION // branches_per_column) + 2
        assignments = [
            _ColumnAssignment(
                column_index=i,
                branches=[
                    (team_id, "p", f"{i:08d}-1111-1111-1111-{team_id:012d}") for team_id in range(branches_per_column)
                ],
            )
            for i in range(column_count)
        ]

        activity_environment.run(run_batched_mutation, RunBatchedMutationInputs(assignments=assignments))

        # Should have submitted MORE THAN ONE mutation, but split at column boundaries.
        assert mock_runner_cls.call_count >= 2
        # Per-call commands must each parse as a single ALTER body (not exceeding cap individually).
        for call in mock_runner_cls.call_args_list:
            commands = call.kwargs["commands"]
            assert len(commands) == 1


class TestChunkAssignmentsByBranchCount:
    def test_packs_into_minimum_chunks(self):
        assignments = [
            _ColumnAssignment(column_index=i, branches=[(j, "p", f"x{j}") for j in range(50)])
            for i in range(10)  # 500 branches total
        ]
        chunks = _chunk_assignments_by_branch_count(assignments, max_branches=200)
        # 500 branches / 200 per chunk → 3 chunks (200, 200, 100)
        assert len(chunks) == 3
        assert sum(len(a.branches) for a in chunks[0]) <= 200
        assert sum(len(a.branches) for a in chunks[1]) <= 200
        assert sum(len(a.branches) for a in chunks[2]) <= 200

    def test_single_oversized_column_lands_in_its_own_chunk(self):
        # A column whose branch count alone exceeds the cap still gets its own chunk —
        # we never split a multiIf across mutations because the multiIf is self-contained.
        big = _ColumnAssignment(column_index=0, branches=[(j, "p", f"x{j}") for j in range(300)])
        small = _ColumnAssignment(column_index=1, branches=[(0, "p", "y0")])
        chunks = _chunk_assignments_by_branch_count([big, small], max_branches=200)
        # First chunk: just the oversized column (300 branches > cap)
        # Second chunk: the small one
        assert len(chunks) == 2
        assert chunks[0] == [big]
        assert chunks[1] == [small]

    def test_returns_empty_for_empty_input(self):
        assert _chunk_assignments_by_branch_count([], max_branches=200) == []


@pytest.mark.django_db(transaction=True)
class TestCompaction:
    """End-to-end exercises of the compaction trigger inside assign_pending_slots."""

    def _fill_pool_close_to_threshold(self, organization) -> list[MaterializedColumnSlot]:
        """Helper: fill the dmat_string pool to within COMPACTION_FREE_COLUMN_THRESHOLD of full
        across many teams (so compaction has room to repack — multiple teams can share a column)."""
        from posthog.models import Team
        from posthog.models.event.sql import DMAT_STRING_COLUMN_COUNT
        from posthog.models.materialized_column_slots import COMPACTION_FREE_COLUMN_THRESHOLD

        free_target = COMPACTION_FREE_COLUMN_THRESHOLD - 1  # 1 fewer than the threshold → triggers
        slots_needed = DMAT_STRING_COLUMN_COUNT - free_target
        slots: list[MaterializedColumnSlot] = []
        # Spread the load across many small teams (one slot each) so per-team uniqueness lets
        # compaction repack everything into a small dense range.
        for i in range(slots_needed):
            team = Team.objects.create(organization=organization, name=f"fill_team_{i}")
            prop_def = PropertyDefinition.objects.create(
                team=team,
                name=f"fill_prop_{i}",
                property_type=PropertyType.String,
                type=PropertyDefinition.Type.EVENT,
            )
            slot = MaterializedColumnSlot.objects.create(
                team=team,
                property_definition=prop_def,
                property_type=PropertyType.String,
                slot_index=i,
                state=MaterializedColumnSlotState.READY,
            )
            slots.append(slot)
        return slots

    def test_compaction_triggers_when_free_columns_drop_below_threshold(self, organization, activity_environment):
        ready_slots = self._fill_pool_close_to_threshold(organization)

        result = activity_environment.run(
            assign_pending_slots,
            AssignPendingSlotsInputs(workflow_id="wf-test"),
        )

        # Compaction should have planned a target for every existing READY slot. Each team has
        # only one slot here, so every team's slot can be packed into the small free range.
        assert sorted(result.compacted_slot_ids) == sorted(str(s.id) for s in ready_slots)
        assert result.assigned_slot_ids == []

        # All compacted slots stay READY (uninterrupted reads) with a fresh, low-index target.
        for slot in ready_slots:
            slot.refresh_from_db()
            assert slot.state == MaterializedColumnSlotState.READY
            assert slot.compaction_target_slot_index is not None
            assert slot.compaction_target_slot_index != slot.slot_index

        # Targets cluster in the small free range (the just-freed-up low end of the pool),
        # not scattered across the whole 0..99 range.
        targets = sorted(
            {s.compaction_target_slot_index for s in ready_slots if s.compaction_target_slot_index is not None}
        )
        # With many teams sharing each column, target span should be much smaller than slot count.
        assert len(targets) <= max(5, len(ready_slots) // 10)

    def test_compaction_does_not_trigger_when_pool_has_capacity(self, team, activity_environment):
        # One ready slot, plenty of free columns.
        prop_def = PropertyDefinition.objects.create(
            team=team,
            name="solo",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop_def,
            property_type=PropertyType.String,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
        )

        result = activity_environment.run(
            assign_pending_slots,
            AssignPendingSlotsInputs(workflow_id="wf-test"),
        )

        assert result.compacted_slot_ids == []
        slot.refresh_from_db()
        assert slot.compaction_target_slot_index is None

    def test_finalize_compaction_swaps_slot_index_to_target(self, team, activity_environment):
        prop_def = PropertyDefinition.objects.create(
            team=team,
            name="p",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop_def,
            property_type=PropertyType.String,
            slot_index=42,
            compaction_target_slot_index=3,
            state=MaterializedColumnSlotState.READY,
        )

        swapped = activity_environment.run(
            finalize_compaction,
            FinalizeCompactionInputs(slot_ids=[str(slot.id)]),
        )

        assert swapped == 1
        slot.refresh_from_db()
        assert slot.slot_index == 3
        assert slot.compaction_target_slot_index is None
        # State stays READY throughout — HogQL just transparently switches columns.
        assert slot.state == MaterializedColumnSlotState.READY

    def test_finalize_compaction_skips_slots_with_no_target(self, team, activity_environment):
        prop_def = PropertyDefinition.objects.create(
            team=team,
            name="p",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop_def,
            property_type=PropertyType.String,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
        )

        swapped = activity_environment.run(
            finalize_compaction,
            FinalizeCompactionInputs(slot_ids=[str(slot.id)]),
        )

        assert swapped == 0
        slot.refresh_from_db()
        assert slot.slot_index == 0
