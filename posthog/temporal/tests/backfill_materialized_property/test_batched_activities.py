"""Tests for the weekly batched dmat backfill activities (PENDING flow)."""

import pytest
from unittest.mock import MagicMock, patch

from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.temporal.backfill_materialized_property.activities import (
    ActivateSlotsInputs,
    AssignCompactionTargetsInputs,
    AssignPendingColumnsInputs,
    FailSlotsInputs,
    FinalizeCompactionInputs,
    PopulateSlotAssignmentsInputs,
    RunBatchedMutationInputs,
    _build_dict_backed_update_command,
    _ColumnAssignment,
    _plan_column_assignments,
    _SlotBranch,
    activate_slots,
    assign_compaction_targets,
    assign_pending_columns,
    compute_cycle_marker_int,
    fail_slots,
    finalize_compaction,
    populate_slot_assignments,
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
        team_ids = {b.team_id for b in plan[0].branches}
        assert team_ids == {team_a.id, team_b.id}

    def test_same_team_with_two_pending_uses_two_columns(self, team):
        slot_one = _make_pending_slot(team, "browser")
        slot_two = _make_pending_slot(team, "utm_source")

        plan = _plan_column_assignments([slot_one, slot_two], used_indexes_by_team={})

        assert {a.column_index for a in plan} == {0, 1}
        # Each column has exactly one branch for this team.
        for assignment in plan:
            assert len(assignment.branches) == 1
            assert assignment.branches[0].team_id == team.id

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


class TestBuildDictBackedUpdateCommand:
    def test_emits_one_set_clause_per_column_with_dict_dispatch(self):
        # Branches list is unused by the dict-backed builder but stays on _ColumnAssignment
        # because the assign_* activities still populate it (vestigial — see plan).
        assignments = [
            _ColumnAssignment(column_index=12, branches=[]),
            _ColumnAssignment(column_index=13, branches=[]),
        ]
        command, params = _build_dict_backed_update_command(assignments, cycle_marker_int=12345)

        # One SET per column, dispatched via dictHas+dictGetString. The trailing dmat_string_<idx>
        # branch is the no-op fallback when the dict has no entry for (team_id, idx).
        assert "dmat_string_12 = if(dictHas(" in command
        assert "dmat_string_13 = if(dictHas(" in command
        # The dictionary key includes column_index so different (team, idx) pairs lookup independently.
        assert "(team_id, 12)" in command
        assert "(team_id, 13)" in command
        assert "dictGetString('dmat_slot_assignments_dict', 'property_name'," in command
        # Extract wrapper must stay byte-identical to `_generate_property_extraction_sql`.
        assert "replaceRegexpAll(" in command
        assert "JSONExtractRaw(properties," in command

    def test_where_clause_uses_in_subselect_against_dict_table(self):
        assignments = [_ColumnAssignment(column_index=7, branches=[])]
        command, _params = _build_dict_backed_update_command(assignments, cycle_marker_int=99999)

        # The WHERE prunes parts via primary-key team_id IN list, sourced from the dict-source
        # CH table (constant-size SQL regardless of how many teams are in the dict).
        assert "WHERE team_id IN (SELECT DISTINCT team_id FROM dmat_slot_assignments)" in command

    def test_cycle_marker_appears_as_no_op_where_conjunct(self):
        assignments = [_ColumnAssignment(column_index=7, branches=[])]
        command, _params = _build_dict_backed_update_command(assignments, cycle_marker_int=12345)

        # Marker terminates the WHERE so MutationRunner's formatted-SQL dedup distinguishes cycles.
        assert command.endswith("AND 12345 = 12345"), command

    def test_different_cycle_markers_produce_different_sql(self):
        assignments = [_ColumnAssignment(column_index=3, branches=[])]
        command_a, _ = _build_dict_backed_update_command(assignments, cycle_marker_int=1)
        command_b, _ = _build_dict_backed_update_command(assignments, cycle_marker_int=2)
        assert command_a != command_b

    def test_same_cycle_marker_produces_identical_sql(self):
        # Within a cycle, retries must produce byte-identical SQL so MutationRunner reattaches.
        assignments = [_ColumnAssignment(column_index=3, branches=[])]
        command_a, params_a = _build_dict_backed_update_command(assignments, cycle_marker_int=42)
        command_b, params_b = _build_dict_backed_update_command(assignments, cycle_marker_int=42)
        assert command_a == command_b
        assert params_a == params_b

    def test_sql_size_is_independent_of_team_count(self):
        # The point of the dict-based design: SQL stays constant size regardless of adoption.
        # We verify by changing the (vestigial) branches list across runs and asserting size.
        few_teams = [_ColumnAssignment(column_index=3, branches=[_SlotBranch(1, "p", "x")])]
        many_teams = [
            _ColumnAssignment(column_index=3, branches=[_SlotBranch(t, f"prop_{t}", f"slot-{t}") for t in range(1000)])
        ]
        cmd_few, _ = _build_dict_backed_update_command(few_teams, cycle_marker_int=42)
        cmd_many, _ = _build_dict_backed_update_command(many_teams, cycle_marker_int=42)
        assert cmd_few == cmd_many, "dict-backed SQL must not depend on per-column branch count"

    def test_returns_empty_params_dict(self):
        # Property names live in the dict at runtime, not as query parameters.
        assignments = [_ColumnAssignment(column_index=0, branches=[])]
        _command, params = _build_dict_backed_update_command(assignments, cycle_marker_int=1)
        assert params == {}

    def test_empty_assignments_raise(self):
        with pytest.raises(ValueError, match="no assignments"):
            _build_dict_backed_update_command([], cycle_marker_int=1)


class TestCycleMarkerEmbedding:
    def test_same_workflow_run_id_yields_same_int(self):
        run_id = "01234567-89ab-cdef-0123-456789abcdef"
        assert compute_cycle_marker_int(run_id) == compute_cycle_marker_int(run_id)

    def test_different_workflow_run_ids_yield_different_ints(self):
        a = compute_cycle_marker_int("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        b = compute_cycle_marker_int("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        assert a != b

    def test_marker_fits_in_32_bits(self):
        marker = compute_cycle_marker_int("any-run-id-here")
        # Embedded as a literal in WHERE — must be a positive 32-bit-ish int so the formatted
        # SQL stays compact and CH treats it as a UInt32 constant.
        assert 0 <= marker < 2**32


@pytest.mark.django_db(transaction=True)
class TestAssignPendingColumns:
    def test_transitions_pending_slots_to_backfill_with_indexes(self, team, activity_environment):
        slot_a = _make_pending_slot(team, "browser")
        slot_b = _make_pending_slot(team, "utm_source")

        result = activity_environment.run(
            assign_pending_columns,
            AssignPendingColumnsInputs(run_id="wf-test"),
        )

        assert sorted(result.assigned_slot_ids) == sorted([str(slot_a.id), str(slot_b.id)])
        slot_a.refresh_from_db()
        slot_b.refresh_from_db()
        assert slot_a.state == MaterializedColumnSlotState.BACKFILL
        assert slot_b.state == MaterializedColumnSlotState.BACKFILL
        assert slot_a.slot_index is not None
        assert slot_b.slot_index is not None
        assert slot_a.slot_index != slot_b.slot_index
        assert slot_a.backfill_temporal_run_id == "wf-test"

    def test_no_pending_slots_returns_empty_plan(self, team, activity_environment):
        result = activity_environment.run(
            assign_pending_columns,
            AssignPendingColumnsInputs(run_id="wf-test"),
        )

        assert result.assigned_slot_ids == []
        assert result.assignments == []

    def test_reclaims_backfill_slots_from_the_same_workflow_run(self, team, activity_environment):
        """Activity-retry case: PENDING→BACKFILL committed, but Temporal didn't record completion.
        Re-running the activity must pick up the already-claimed slots and include them in the
        assignment plan so the mutation step still runs against them."""
        prop_def = PropertyDefinition.objects.create(
            team=team,
            name="reclaimable",
            type=PropertyDefinition.Type.EVENT,
        )
        existing = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop_def,
            slot_index=7,
            state=MaterializedColumnSlotState.BACKFILL,
            backfill_temporal_run_id="run-abc",
        )

        result = activity_environment.run(
            assign_pending_columns,
            AssignPendingColumnsInputs(run_id="run-abc"),
        )

        # The reclaimed slot should be in assigned_slot_ids and a column 7 assignment should
        # exist so the mutation runs against the slot's existing column.
        assert str(existing.id) in result.assigned_slot_ids
        assert any(a.column_index == 7 for a in result.assignments), "missing reclaim assignment for column 7"

    def test_does_not_reclaim_backfill_slots_from_a_different_run(self, team, activity_environment):
        """Stranded BACKFILL slots from a previous run are NOT auto-reclaimed — the activity
        logs a warning and an operator handles the recovery via the API. Otherwise we'd risk
        re-running a mutation that may have already completed against a column an operator
        re-purposed."""
        prop_def = PropertyDefinition.objects.create(
            team=team,
            name="stranded",
            type=PropertyDefinition.Type.EVENT,
        )
        stranded = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop_def,
            slot_index=7,
            state=MaterializedColumnSlotState.BACKFILL,
            backfill_temporal_run_id="run-OLD",
        )

        result = activity_environment.run(
            assign_pending_columns,
            AssignPendingColumnsInputs(run_id="run-NEW"),
        )

        assert str(stranded.id) not in result.assigned_slot_ids
        # And the slot stays in BACKFILL with its old run_id intact — operator must intervene.
        stranded.refresh_from_db()
        assert stranded.state == MaterializedColumnSlotState.BACKFILL
        assert stranded.backfill_temporal_run_id == "run-OLD"

    def test_avoids_collisions_with_existing_ready_slot_indexes(self, team, activity_environment):
        # Pre-existing READY slot at index 0 means the new pending slot must land elsewhere.
        existing_prop = PropertyDefinition.objects.create(
            team=team,
            name="existing",
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=existing_prop,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
        )

        new_slot = _make_pending_slot(team, "new_prop")

        activity_environment.run(
            assign_pending_columns,
            AssignPendingColumnsInputs(run_id="wf-test"),
        )

        new_slot.refresh_from_db()
        assert new_slot.slot_index == 1

    def test_refuses_to_allocate_when_free_pool_below_threshold(self, organization, activity_environment):
        """Hard safety: allocating below the compaction threshold could starve compaction of
        dense targets and brick PENDING allocation indefinitely."""
        from posthog.models import Team
        from posthog.models.event.sql import DMAT_STRING_COLUMN_COUNT
        from posthog.models.materialized_column_slots import COMPACTION_FREE_COLUMN_THRESHOLD

        # Fill the pool to free_count = threshold - 1 across many small teams.
        free_target = COMPACTION_FREE_COLUMN_THRESHOLD - 1
        slots_needed = DMAT_STRING_COLUMN_COUNT - free_target
        for i in range(slots_needed):
            fill_team = Team.objects.create(organization=organization, name=f"fill_team_{i}")
            prop_def = PropertyDefinition.objects.create(
                team=fill_team,
                name=f"fill_prop_{i}",
                type=PropertyDefinition.Type.EVENT,
            )
            MaterializedColumnSlot.objects.create(
                team=fill_team,
                property_definition=prop_def,
                slot_index=i,
                state=MaterializedColumnSlotState.READY,
            )

        # Add a fresh team with a PENDING slot that should NOT be allocated this run.
        pending_team = Team.objects.create(organization=organization, name="pending_team")
        pending_slot = _make_pending_slot(pending_team, "browser")

        result = activity_environment.run(
            assign_pending_columns,
            AssignPendingColumnsInputs(run_id="wf-test"),
        )

        assert result.assigned_slot_ids == []
        assert result.assignments == []

        # Slot stays PENDING with no slot_index — next cycle will pick it up after compaction
        # has had a chance to free columns.
        pending_slot.refresh_from_db()
        assert pending_slot.state == MaterializedColumnSlotState.PENDING
        assert pending_slot.slot_index is None

    def test_reclaimed_slots_pass_through_even_below_threshold(self, organization, activity_environment):
        """The threshold safety only blocks FRESH allocation — reclaimed slots are already
        past the allocation point and blocking them would strand them."""
        from posthog.models import Team
        from posthog.models.event.sql import DMAT_STRING_COLUMN_COUNT
        from posthog.models.materialized_column_slots import COMPACTION_FREE_COLUMN_THRESHOLD

        free_target = COMPACTION_FREE_COLUMN_THRESHOLD - 1
        slots_needed = DMAT_STRING_COLUMN_COUNT - free_target - 1  # leave room for the reclaimed slot's column.
        for i in range(slots_needed):
            fill_team = Team.objects.create(organization=organization, name=f"fill_team_{i}")
            prop_def = PropertyDefinition.objects.create(
                team=fill_team,
                name=f"fill_prop_{i}",
                type=PropertyDefinition.Type.EVENT,
            )
            MaterializedColumnSlot.objects.create(
                team=fill_team,
                property_definition=prop_def,
                slot_index=i,
                state=MaterializedColumnSlotState.READY,
            )

        # Reclaimed slot — already in BACKFILL with run_id matching this run.
        reclaim_team = Team.objects.create(organization=organization, name="reclaim_team")
        reclaim_prop = PropertyDefinition.objects.create(
            team=reclaim_team,
            name="reclaimed",
            type=PropertyDefinition.Type.EVENT,
        )
        reclaimed = MaterializedColumnSlot.objects.create(
            team=reclaim_team,
            property_definition=reclaim_prop,
            slot_index=slots_needed,  # next free index
            state=MaterializedColumnSlotState.BACKFILL,
            backfill_temporal_run_id="wf-test",
        )

        result = activity_environment.run(
            assign_pending_columns,
            AssignPendingColumnsInputs(run_id="wf-test"),
        )

        # Reclaimed slot makes it into the assignment plan (mutation will re-run idempotently).
        assert str(reclaimed.id) in result.assigned_slot_ids
        assert any(a.column_index == slots_needed for a in result.assignments)

    def test_avoids_in_flight_compaction_targets_within_team(self, team, activity_environment):
        """In-flight compaction targets count as in-use, so PENDING allocation can't collide
        with compaction reservations across workflow runs.
        """
        existing_prop = PropertyDefinition.objects.create(
            team=team,
            name="being_compacted",
            type=PropertyDefinition.Type.EVENT,
        )
        # Slot is READY on column 0 and is in-flight compacting to column 1.
        MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=existing_prop,
            slot_index=0,
            compaction_target_slot_index=1,
            state=MaterializedColumnSlotState.READY,
        )

        new_slot = _make_pending_slot(team, "new_prop")

        activity_environment.run(
            assign_pending_columns,
            AssignPendingColumnsInputs(run_id="wf-test"),
        )

        new_slot.refresh_from_db()
        # Must NOT land on column 0 (already used by other slot's slot_index) or column 1
        # (already used by other slot's compaction_target_slot_index). Greedy planner picks 2.
        assert new_slot.slot_index == 2


@pytest.mark.django_db(transaction=True)
class TestActivateAndFailSlots:
    def test_activate_slots_transitions_backfill_to_ready(self, team, activity_environment):
        prop = PropertyDefinition.objects.create(
            team=team,
            name="p",
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop,
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
            type=PropertyDefinition.Type.EVENT,
        )
        # ERROR slot should not be transitioned to READY by activate_slots.
        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop,
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
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop,
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
        activity_environment.run(
            run_batched_mutation,
            RunBatchedMutationInputs(assignments=[], cycle_marker_int=1),
        )
        mock_get_cluster.assert_not_called()
        mock_runner_cls.assert_not_called()

    @patch("posthog.temporal.backfill_materialized_property.activities.AlterTableMutationRunner")
    @patch("posthog.temporal.backfill_materialized_property.activities.get_cluster")
    def test_invokes_alter_table_runner_with_dict_backed_command(
        self,
        mock_get_cluster,
        mock_runner_cls,
        activity_environment,
    ):
        assignments = [_ColumnAssignment(column_index=7, branches=[])]
        runner_instance = mock_runner_cls.return_value

        activity_environment.run(
            run_batched_mutation,
            RunBatchedMutationInputs(assignments=assignments, cycle_marker_int=42),
        )

        mock_runner_cls.assert_called_once()
        call_kwargs = mock_runner_cls.call_args.kwargs
        assert call_kwargs["table"] == "sharded_events"
        commands = call_kwargs["commands"]
        assert len(commands) == 1
        (command,) = commands
        # Dict-backed dispatch over the column.
        assert "dmat_string_7 = if(dictHas(" in command
        # Cycle marker appended for cross-cycle dedup.
        assert command.endswith("AND 42 = 42")
        # Empty params: property names live in the dict, not the query.
        assert call_kwargs["parameters"] == {}

        runner_instance.run_on_shards.assert_called_once_with(mock_get_cluster.return_value)


@pytest.mark.django_db(transaction=True)
class TestPopulateSlotAssignments:
    """The activity reads READY+BACKFILL slots from Postgres and pushes them as a CH-side
    table that the dmat_slot_assignments_dict reads from. Both PENDING and compaction
    workflows call it after their assign_* step."""

    def _fake_cluster_with_hosts(self, host_count: int = 3, fail_on_host: int | None = None) -> MagicMock:
        """Build a MagicMock ClickhouseCluster whose `map_all_hosts(fn)` invokes `fn` once per
        synthetic host. If `fail_on_host` is set, that host's call raises, and the FuturesMap's
        .result() raises ExceptionGroup like the real cluster does."""
        cluster = MagicMock()

        def map_all_hosts(fn):
            results: dict[str, object] = {}
            errors: dict[str, Exception] = {}
            for host_idx in range(host_count):
                client = MagicMock()
                try:
                    if fail_on_host is not None and host_idx == fail_on_host:
                        raise RuntimeError(f"populate failed on host {host_idx}")
                    results[f"host-{host_idx}"] = fn(client)
                except Exception as e:
                    errors[f"host-{host_idx}"] = e

            futures_map = MagicMock()

            def result():
                if errors:
                    raise ExceptionGroup("simulated cluster failure", list(errors.values()))
                return results

            futures_map.result = result
            futures_map.values = lambda: results.values()
            return futures_map

        cluster.map_all_hosts = MagicMock(side_effect=map_all_hosts)
        return cluster

    @patch("posthog.temporal.backfill_materialized_property.activities.get_cluster")
    def test_truncates_inserts_and_reloads_on_every_host(self, mock_get_cluster, team, activity_environment):
        prop_a = PropertyDefinition.objects.create(team=team, name="browser", type=PropertyDefinition.Type.EVENT)
        prop_b = PropertyDefinition.objects.create(team=team, name="plan", type=PropertyDefinition.Type.EVENT)
        MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop_a,
            slot_index=3,
            state=MaterializedColumnSlotState.READY,
        )
        MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop_b,
            slot_index=7,
            compaction_target_slot_index=2,
            state=MaterializedColumnSlotState.READY,
        )

        # Capture every SQL string each "host" sees so we can assert the order: TRUNCATE, INSERT, RELOAD.
        all_executed: list[list] = []

        def map_all_hosts(fn):
            futures_map = MagicMock()

            def run_per_host():
                results = {}
                for host_idx in range(3):
                    executed_per_host: list = []
                    client = MagicMock()
                    client.execute = lambda sql, *args, _log=executed_per_host: _log.append((sql, args))
                    results[f"host-{host_idx}"] = fn(client)
                    all_executed.append(executed_per_host)
                return results

            stored = run_per_host()
            futures_map.result = lambda: stored
            futures_map.values = stored.values
            return futures_map

        cluster = MagicMock()
        cluster.map_all_hosts = MagicMock(side_effect=map_all_hosts)
        mock_get_cluster.return_value = cluster

        result = activity_environment.run(populate_slot_assignments, PopulateSlotAssignmentsInputs())

        # Three rows: (team, slot_index=3, browser), (team, slot_index=7, plan), (team, target=2, plan).
        assert result.rows_written == 3

        # 3 hosts populated + 3 hosts reloaded → 6 host-fn invocations total.
        # Each populate host sees [TRUNCATE, INSERT]; each reload host sees [RELOAD].
        truncate_count = sum(1 for batch in all_executed for sql, _ in batch if "TRUNCATE TABLE" in sql)
        insert_count = sum(1 for batch in all_executed for sql, _ in batch if "INSERT INTO" in sql)
        reload_count = sum(1 for batch in all_executed for sql, _ in batch if "SYSTEM RELOAD DICTIONARY" in sql)
        assert truncate_count == 3
        assert insert_count == 3
        assert reload_count == 3

        # Within each populate host, TRUNCATE precedes INSERT.
        for batch in all_executed:
            sql_seq = [s for s, _ in batch]
            if any("TRUNCATE TABLE" in s for s in sql_seq):
                truncate_idx = next(i for i, s in enumerate(sql_seq) if "TRUNCATE TABLE" in s)
                insert_idx = next(i for i, s in enumerate(sql_seq) if "INSERT INTO" in s)
                assert truncate_idx < insert_idx

    @patch("posthog.temporal.backfill_materialized_property.activities.get_cluster")
    def test_aborts_before_reload_when_a_host_populate_fails(self, mock_get_cluster, team, activity_environment):
        prop = PropertyDefinition.objects.create(team=team, name="browser", type=PropertyDefinition.Type.EVENT)
        MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop,
            slot_index=3,
            state=MaterializedColumnSlotState.READY,
        )

        # First map_all_hosts call (populate) fails on host 1; second call (reload) must never happen.
        call_count = {"map_all_hosts": 0}

        def map_all_hosts(fn):
            call_count["map_all_hosts"] += 1
            futures_map = MagicMock()
            if call_count["map_all_hosts"] == 1:
                # Populate raises on the second host.
                def result():
                    raise ExceptionGroup("populate failed", [RuntimeError("host 1 down")])

                futures_map.result = result
            else:
                # Reload should never reach here.
                futures_map.result = MagicMock(return_value={})
            return futures_map

        cluster = MagicMock()
        cluster.map_all_hosts = MagicMock(side_effect=map_all_hosts)
        mock_get_cluster.return_value = cluster

        with pytest.raises(BaseException) as excinfo:
            activity_environment.run(populate_slot_assignments, PopulateSlotAssignmentsInputs())

        # Either the ExceptionGroup itself or the activity's wrapping raises — what matters
        # is that the second map_all_hosts call (reload) never happened.
        assert "populate failed" in str(excinfo.value) or "host 1 down" in str(excinfo.value)
        assert call_count["map_all_hosts"] == 1, "reload must not be issued when populate fails on any host"

    @patch("posthog.temporal.backfill_materialized_property.activities.get_cluster")
    def test_idempotent_under_retry(self, mock_get_cluster, team, activity_environment):
        """Running the activity twice in a row with no Postgres state changes between
        produces the same end state on every host. TRUNCATE+INSERT is end-state idempotent."""
        prop = PropertyDefinition.objects.create(team=team, name="browser", type=PropertyDefinition.Type.EVENT)
        MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop,
            slot_index=3,
            state=MaterializedColumnSlotState.READY,
        )

        cluster = self._fake_cluster_with_hosts(host_count=2)
        mock_get_cluster.return_value = cluster

        first = activity_environment.run(populate_slot_assignments, PopulateSlotAssignmentsInputs())
        second = activity_environment.run(populate_slot_assignments, PopulateSlotAssignmentsInputs())

        assert first.rows_written == second.rows_written
        # Two activity invocations × (1 populate + 1 reload) per invocation × per-host execution
        # — what matters is each call dispatched the same operations.


@pytest.mark.django_db(transaction=True)
class TestAssignCompactionTargets:
    """End-to-end exercises of the dedicated compaction activity (split out from PENDING)."""

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
                type=PropertyDefinition.Type.EVENT,
            )
            slot = MaterializedColumnSlot.objects.create(
                team=team,
                property_definition=prop_def,
                slot_index=i,
                state=MaterializedColumnSlotState.READY,
            )
            slots.append(slot)
        return slots

    def test_compaction_triggers_when_free_columns_drop_below_threshold(self, organization, activity_environment):
        ready_slots = self._fill_pool_close_to_threshold(organization)

        result = activity_environment.run(
            assign_compaction_targets,
            AssignCompactionTargetsInputs(run_id="wf-test"),
        )

        # Compaction should have planned a target for every existing READY slot. Each team has
        # only one slot here, so every team's slot can be packed into the small free range.
        assert sorted(result.compacted_slot_ids) == sorted(str(s.id) for s in ready_slots)

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
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop_def,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
        )

        result = activity_environment.run(
            assign_compaction_targets,
            AssignCompactionTargetsInputs(run_id="wf-test"),
        )

        assert result.compacted_slot_ids == []
        assert result.assignments == []
        slot.refresh_from_db()
        assert slot.compaction_target_slot_index is None

    def test_does_not_touch_pending_slots(self, team, activity_environment):
        """Compaction activity must never transition PENDING→BACKFILL — that's the PENDING
        workflow's job. A PENDING slot in the table while compaction runs should stay
        PENDING with no slot_index assigned, even if compaction would otherwise fire."""
        pending = _make_pending_slot(team, "p")

        activity_environment.run(
            assign_compaction_targets,
            AssignCompactionTargetsInputs(run_id="wf-test"),
        )

        pending.refresh_from_db()
        assert pending.state == MaterializedColumnSlotState.PENDING
        assert pending.slot_index is None

    def test_resumes_in_flight_targets_without_re_planning(self, team, activity_environment):
        """If a slot already has compaction_target_slot_index set (from a prior run that
        crashed mid-mutation or mid-finalize), the activity must include it in the assignment
        plan as-is so the mutation runner can drive it to completion. We do NOT re-plan or
        clear the target — the mutation runner is idempotent and re-targeting would risk
        plugin-server caches missing dual-writes during the cache refresh window.

        When in-flight targets exist, the fresh-trigger path is also suppressed for this run
        even if the threshold check would otherwise fire (the next firing handles fresh
        compaction once in-flight ones are finalized)."""
        prop_def = PropertyDefinition.objects.create(
            team=team,
            name="being_compacted",
            type=PropertyDefinition.Type.EVENT,
        )
        in_flight = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop_def,
            slot_index=42,
            compaction_target_slot_index=3,
            state=MaterializedColumnSlotState.READY,
        )

        result = activity_environment.run(
            assign_compaction_targets,
            AssignCompactionTargetsInputs(run_id="wf-different-run"),
        )

        assert str(in_flight.id) in result.compacted_slot_ids
        # Assignment plan keeps the existing target column — not a re-planned one.
        assert any(a.column_index == 3 for a in result.assignments), "expected resume of column 3"

        # In-flight target stays exactly as it was — activity must not modify it on resume.
        in_flight.refresh_from_db()
        assert in_flight.compaction_target_slot_index == 3
        assert in_flight.slot_index == 42

    def test_finalize_compaction_swaps_slot_index_to_target(self, team, activity_environment):
        prop_def = PropertyDefinition.objects.create(
            team=team,
            name="p",
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop_def,
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
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop_def,
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
