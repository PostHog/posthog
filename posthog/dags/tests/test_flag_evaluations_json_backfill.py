import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from unittest.mock import MagicMock, patch

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole
from posthog.clickhouse.query_tagging import DagsterTags
from posthog.dags.deletes import deletes_job
from posthog.dags.flag_evaluations_json_backfill import (
    CopyUnit,
    FlagEvaluationsJsonBackfillConfig,
    UnitBackfill,
    compare_counts,
    cutover_problems,
    flag_evaluations_json_backfill_job,
    flag_evaluations_json_parity_job,
    is_expired,
    plan_units,
    resolve_days,
)
from posthog.dags.tests.test_flag_evaluations_backfill import SourceEvent, flag_called, seed_source_events
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

TEAM_ONE, TEAM_TWO = 1, 2
# The window the end-to-end tests copy. It starts well inside the retention window and ends tomorrow, so it
# includes today, the day that dual-write starts.
WINDOW_DAYS = 3


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC)


def window(now: datetime) -> dict[str, str]:
    return {"start_date": str((now - timedelta(days=WINDOW_DAYS)).date())}


RECENT = flag_called("recent", TEAM_ONE, timedelta(days=2, hours=12))
TODAY = flag_called("today", TEAM_ONE, timedelta(0))
# The events column holds '' when an event arrives without person properties. The new table needs '{}'.
NO_PERSON_PROPERTIES = replace(flag_called("no_person_properties", TEAM_TWO, timedelta(days=1)), person_properties="")
OUTSIDE_WINDOW = flag_called("outside_window", TEAM_ONE, timedelta(days=30))
NOT_A_FLAG_CALL = replace(flag_called("not_a_flag_call", TEAM_ONE, timedelta(days=1)), event="$pageview")
EMPTY_FLAG_KEY = SourceEvent(
    label="empty_flag_key",
    team_id=TEAM_ONE,
    age=timedelta(days=1),
    properties={"$feature_flag": "", "$feature_flag_response": "control"},
)
NUMERIC_FLAG_KEY = SourceEvent(
    label="numeric_flag_key",
    team_id=TEAM_ONE,
    age=timedelta(days=1),
    properties={"$feature_flag": 7, "$feature_flag_response": "control"},
)
# The calls of an organization on mode 2 after it moved. Events does not hold them.
LEGACY_ONLY = flag_called("legacy_only", TEAM_TWO, timedelta(days=1, hours=6))
OTHER_TEAM_LEGACY_ONLY = flag_called("other_team_legacy_only", 99, timedelta(days=1, hours=6))
PRE_MOVE_IN_BOTH = flag_called("pre_move_in_both", TEAM_TWO, timedelta(days=2, hours=6))

ELIGIBLE_FROM_EVENTS = [RECENT, TODAY, NO_PERSON_PROPERTIES]
INELIGIBLE_IN_EVENTS = [OUTSIDE_WINDOW, NOT_A_FLAG_CALL, EMPTY_FLAG_KEY, NUMERIC_FLAG_KEY]

KAFKA_ROW = SourceEvent(label="kafka_row", team_id=TEAM_ONE, age=timedelta(days=1, hours=2), properties={})


def seed_legacy_row(
    cluster: ClickhouseCluster, now: datetime, event: SourceEvent, *, partition: int = 0, offset: int = 0
) -> None:
    row = (
        event.team_id,
        event.distinct_id,
        uuid5(NAMESPACE_URL, event.distinct_id),
        event.uuid,
        event.event,
        json.dumps(event.properties),
        now - event.age,
        now - event.age,
        partition,
        offset,
    )

    def insert(client: Client) -> None:
        client.execute(
            """INSERT INTO writable_flag_evaluations
            (team_id, distinct_id, person_id, uuid, event, properties, timestamp, _timestamp, _partition, _offset)
            VALUES""",
            [row],
        )

    cluster.any_host(insert).result()


def seed_json_kafka_row(cluster: ClickhouseCluster, now: datetime, event: SourceEvent, partition: int, offset: int):
    row = (
        event.team_id,
        event.distinct_id,
        uuid5(NAMESPACE_URL, event.distinct_id),
        event.uuid,
        now - event.age,
        now - event.age + timedelta(seconds=1),
        now - event.age,
        partition,
        offset,
    )

    def insert(client: Client) -> None:
        client.execute(
            """INSERT INTO writable_flag_evaluations_json
            (team_id, distinct_id, person_id, uuid, timestamp, inserted_at, _timestamp, _partition, _offset)
            VALUES""",
            [row],
        )

    cluster.any_host(insert).result()


def seed_cutover_rows(cluster: ClickhouseCluster, now: datetime, event: SourceEvent = KAFKA_ROW) -> None:
    """Rows through Kafka in both tables, with the legacy consumer group ahead of the new one."""
    seed_legacy_row(cluster, now, event, partition=0, offset=50)
    seed_json_kafka_row(cluster, now, event, partition=0, offset=40)


def stored(cluster: ClickhouseCluster) -> dict[str, tuple]:
    labels = {
        event.uuid: event.label
        for event in [
            *ELIGIBLE_FROM_EVENTS,
            *INELIGIBLE_IN_EVENTS,
            LEGACY_ONLY,
            PRE_MOVE_IN_BOTH,
            OTHER_TEAM_LEGACY_ONLY,
        ]
    }

    def select(client: Client) -> list[tuple]:
        return client.execute(
            """SELECT uuid, flag_key, response, toString(properties.`$session_id`), toString(person_properties.email),
                inserted_at = timestamp, _partition, _offset, captured_at = created_at, team_id
            FROM flag_evaluations_json
            WHERE _partition = 0 AND _offset = 0"""
        )

    rows = cluster.any_host(select).result()
    return {
        labels.get(uuid, str(uuid)): (
            flag_key,
            response,
            session_id,
            person_properties,
            bool(own_time),
            bool(captured),
            team,
        )
        for uuid, flag_key, response, session_id, person_properties, own_time, _, _, captured, team in rows
    }


def copied(event: SourceEvent) -> tuple:
    return (
        str(event.properties["$feature_flag"]),
        str(event.properties["$feature_flag_response"]),
        str(event.properties["$session_id"]),
        json.loads(event.person_properties or "{}").get("email", ""),
        True,
        True,
        event.team_id,
    )


def run_backfill(
    cluster: ClickhouseCluster, instance: dagster.DagsterInstance | None = None, **overrides: Any
) -> dagster.ExecuteInProcessResult:
    # The default disk floor exceeds the free space on a development machine, so every run turns the floor off.
    config = FlagEvaluationsJsonBackfillConfig(**{"min_free_bytes": 0, **overrides})
    return flag_evaluations_json_backfill_job.execute_in_process(
        run_config=dagster.RunConfig(ops={"plan_flag_evaluations_json_backfill": config}),
        resources={"cluster": cluster},
        instance=instance or dagster.DagsterInstance.ephemeral(),
        raise_on_error=False,
    )


def copied_rows(result: dagster.ExecuteInProcessResult) -> int:
    return result.output_for_node("copy_flag_evaluations_json")


@pytest.mark.django_db
@pytest.mark.parametrize("runs", [1, 2], ids=["first_run", "second_run_copies_nothing_new"])
def test_backfill_copies_each_eligible_event_once_and_computes_the_typed_columns(
    cluster: ClickhouseCluster, now: datetime, runs: int
) -> None:
    seed_source_events(cluster, now, [*ELIGIBLE_FROM_EVENTS, *INELIGIBLE_IN_EVENTS])
    seed_cutover_rows(cluster, now)

    results = [run_backfill(cluster, **window(now)) for _ in range(runs)]

    assert all(result.success for result in results)
    assert copied_rows(results[0]) == len(ELIGIBLE_FROM_EVENTS)
    assert [copied_rows(result) for result in results[1:]] == [0] * (runs - 1)
    assert stored(cluster) == {event.label: copied(event) for event in ELIGIBLE_FROM_EVENTS}


@pytest.mark.django_db
def test_backfill_skips_a_call_the_kafka_path_already_wrote(cluster: ClickhouseCluster, now: datetime) -> None:
    seed_source_events(cluster, now, [RECENT])
    seed_cutover_rows(cluster, now)
    seed_json_kafka_row(cluster, now, RECENT, partition=0, offset=41)

    result = run_backfill(cluster, **window(now))

    assert result.success
    assert copied_rows(result) == 0
    assert stored(cluster) == {}


@pytest.mark.django_db
def test_backfill_reads_flag_evaluations_for_the_teams_that_events_lacks_and_copies_a_call_in_both_once(
    cluster: ClickhouseCluster, now: datetime
) -> None:
    seed_source_events(cluster, now, [PRE_MOVE_IN_BOTH])
    seed_legacy_row(cluster, now, PRE_MOVE_IN_BOTH)
    seed_legacy_row(cluster, now, LEGACY_ONLY)
    seed_legacy_row(cluster, now, OTHER_TEAM_LEGACY_ONLY)
    seed_cutover_rows(cluster, now)

    result = run_backfill(cluster, flag_evaluations_team_ids=[TEAM_TWO], **window(now))

    assert result.success
    assert copied_rows(result) == 2
    stored_rows = stored(cluster)
    assert set(stored_rows) == {PRE_MOVE_IN_BOTH.label, LEGACY_ONLY.label}
    # The events copy wins for a call in both sources, because its day's events unit runs first.
    assert stored_rows[PRE_MOVE_IN_BOTH.label] == copied(PRE_MOVE_IN_BOTH)
    assert stored_rows[LEGACY_ONLY.label][0] == str(LEGACY_ONLY.properties["$feature_flag"])


@pytest.mark.django_db
def test_backfill_reads_flag_evaluations_for_the_teams_of_an_organization_on_mode_2(
    cluster: ClickhouseCluster, now: datetime
) -> None:
    organization = Organization.objects.create(name="Moved to mode 2")
    OrganizationFeatureFlagsConfig.objects.update_or_create(
        organization=organization, defaults={"flag_evaluations_mode": FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY}
    )
    team = Team.objects.create(organization=organization, name="Moved team")
    on_events = Team.objects.create(
        organization=Organization.objects.create(name="Stays on events"), name="Events team"
    )
    OrganizationFeatureFlagsConfig.objects.filter(organization_id=on_events.organization_id).update(
        flag_evaluations_mode=FlagEvaluationsMode.EVENTS
    )
    moved_call = flag_called("moved_call", team.id, timedelta(days=1))
    other_call = flag_called("other_call", on_events.id, timedelta(days=1))
    seed_legacy_row(cluster, now, moved_call)
    seed_legacy_row(cluster, now, other_call)
    seed_cutover_rows(cluster, now)

    result = run_backfill(cluster, **window(now))

    assert result.success
    assert copied_rows(result) == 1


@pytest.mark.django_db
def test_backfill_copies_days_newest_first_includes_today_and_stops_at_the_first_failed_unit(
    cluster: ClickhouseCluster, now: datetime
) -> None:
    seed_cutover_rows(cluster, now)
    ran: list[CopyUnit] = []

    def record_then_fail_on_the_second_day(backfill: UnitBackfill, unit: CopyUnit) -> int:
        ran.append(unit)
        if len({u.day for u in ran}) == 2:
            raise RuntimeError("stop here")
        return 0

    with patch.object(UnitBackfill, "run", autospec=True, side_effect=record_then_fail_on_the_second_day):
        result = run_backfill(cluster, **window(now))

    assert not result.success
    days = [unit.day for unit in ran]
    assert days == sorted(days, reverse=True)
    assert days[0] == (now + timedelta(days=1)).date() - timedelta(days=1)
    assert len(set(days)) == 2


@pytest.mark.django_db
def test_dry_run_counts_the_rows_it_would_copy_and_writes_none(cluster: ClickhouseCluster, now: datetime) -> None:
    seed_source_events(cluster, now, ELIGIBLE_FROM_EVENTS)
    seed_cutover_rows(cluster, now)

    result = run_backfill(cluster, dry_run=True, **window(now))

    assert result.success
    assert copied_rows(result) == len(ELIGIBLE_FROM_EVENTS)
    assert stored(cluster) == {}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "seed, overrides",
    [
        pytest.param(lambda cluster, now: None, {}, id="new_table_has_no_kafka_row"),
        pytest.param(
            lambda cluster, now: (
                seed_legacy_row(cluster, now, replace(KAFKA_ROW, label="legacy"), partition=0, offset=10),
                seed_json_kafka_row(cluster, now, replace(KAFKA_ROW, label="json"), partition=0, offset=40),
            ),
            {},
            id="legacy_consumer_group_stops_before_the_new_one_starts",
        ),
        pytest.param(
            lambda cluster, now: (
                seed_legacy_row(cluster, now, replace(KAFKA_ROW, label="legacy"), partition=0, offset=50),
                seed_json_kafka_row(cluster, now, replace(KAFKA_ROW, label="json"), partition=1, offset=40),
            ),
            {},
            id="partition_missing_from_one_table",
        ),
        pytest.param(
            lambda cluster, now: seed_cutover_rows(cluster, now), {"min_free_bytes": 1 << 60}, id="disk_below_the_floor"
        ),
    ],
)
def test_backfill_copies_nothing_when_a_precondition_fails(
    cluster: ClickhouseCluster, now: datetime, seed: Any, overrides: dict[str, Any]
) -> None:
    seed_source_events(cluster, now, [RECENT])
    seed(cluster, now)

    result = run_backfill(cluster, **window(now), **overrides)

    assert not result.success
    assert stored(cluster) == {}


@pytest.mark.django_db
def test_backfill_names_the_day_and_the_repair_when_a_blocking_run_starts_during_a_copy(
    cluster: ClickhouseCluster, now: datetime
) -> None:
    seed_source_events(cluster, now, [RECENT])
    seed_cutover_rows(cluster, now)
    instance = dagster.DagsterInstance.ephemeral()
    copy = UnitBackfill._copy

    def copy_while_deletes_starts(backfill: UnitBackfill, *args: Any) -> int:
        instance.create_run_for_job(job_def=deletes_job, status=dagster.DagsterRunStatus.STARTED)
        return copy(backfill, *args)

    with patch.object(UnitBackfill, "_copy", autospec=True, side_effect=copy_while_deletes_starts):
        result = run_backfill(
            cluster,
            instance=instance,
            team_ids=[TEAM_ONE],
            start_date=str(RECENT_DAY(now)),
            end_date=str(RECENT_DAY(now) + timedelta(days=1)),
        )

    [failure] = result.get_step_failure_events()
    assert failure.step_failure_data.error is not None
    message = failure.step_failure_data.error.message
    assert f"started while {RECENT_DAY(now)} copied" in message
    assert "DELETE FROM sharded_flag_evaluations_json" in message
    assert "inserted_at = timestamp" in message
    assert f"team_id IN ({TEAM_ONE})" in message


def RECENT_DAY(now: datetime) -> date:
    return (now - RECENT.age).date()


def unit_backfill(cluster: Any = None, **config: Any) -> UnitBackfill:
    return UnitBackfill(
        cluster=cluster or MagicMock(),
        shard_num=1,
        config=FlagEvaluationsJsonBackfillConfig(max_unmerged_parts=0, **config),
        flag_evaluations_team_ids=(),
        instance=dagster.DagsterInstance.ephemeral(),
        run_id="json-backfill-run",
        log=MagicMock(),
        query_tags=DagsterTags(),
        workload=Workload.DEFAULT,
        node_role=NodeRole.ALL,
        job_name=flag_evaluations_json_backfill_job.name,
    )


def test_a_unit_for_a_day_the_ttl_has_expired_copies_nothing() -> None:
    cluster = MagicMock()
    expired = datetime.now(UTC).date() - timedelta(days=100)

    assert unit_backfill(cluster).run(CopyUnit(day=expired, events_shard=1)) == 0
    assert cluster.method_calls == []


@pytest.mark.parametrize(
    "days_ago, expired",
    [
        pytest.param(89, False, id="oldest_day_to_copy"),
        pytest.param(91, False, id="last_day_before_expiry"),
        pytest.param(92, True, id="expires_today"),
    ],
)
def test_a_day_expires_when_its_ttl_day_starts(days_ago: int, expired: bool) -> None:
    today = date(2026, 12, 1)

    assert is_expired(today - timedelta(days=days_ago), today) is expired


TODAY_DATE = date(2026, 12, 1)


@pytest.mark.parametrize(
    "overrides, error",
    [
        pytest.param({"start_date": "2026-09-01"}, "before 2026-09-03", id="start_before_the_earliest_day"),
        pytest.param({"end_date": "2026-12-03"}, "after tomorrow", id="end_after_tomorrow"),
        pytest.param({"start_date": "2026-12-01", "end_date": "2026-12-01"}, "must be before", id="empty_window"),
    ],
)
def test_resolve_days_rejects_an_unsafe_window(overrides: dict[str, str], error: str) -> None:
    with pytest.raises(dagster.Failure, match=error):
        resolve_days(today=TODAY_DATE, **overrides)


def test_resolve_days_runs_from_89_days_ago_through_today_newest_first() -> None:
    days = resolve_days(today=TODAY_DATE)

    assert days[0] == TODAY_DATE
    assert days[-1] == TODAY_DATE - timedelta(days=89)
    assert list(days) == sorted(days, reverse=True)
    assert len(days) == 90


def test_plan_units_orders_each_day_with_events_shards_before_flag_evaluations() -> None:
    days = [date(2026, 12, 2), date(2026, 12, 1)]

    units = plan_units(days, source_shards=[2, 1], flag_evaluations_team_ids=[5])

    assert [(unit.day.day, unit.events_shard) for unit in units] == [
        (2, 1),
        (2, 2),
        (2, None),
        (1, 1),
        (1, 2),
        (1, None),
    ]


def test_plan_units_reads_no_flag_evaluations_when_no_team_needs_it() -> None:
    units = plan_units([date(2026, 12, 1)], source_shards=[1, 2], flag_evaluations_team_ids=[])

    assert [unit.events_shard for unit in units] == [1, 2]


@pytest.mark.parametrize(
    "legacy, new, expected_fragments",
    [
        pytest.param({0: 50, 1: 70}, {0: 40, 1: 70}, [], id="legacy_reaches_every_first_offset"),
        pytest.param({0: 50}, {}, ["no row from Kafka"], id="new_table_empty"),
        pytest.param({}, {0: 40}, ["no row from Kafka"], id="legacy_table_empty"),
        pytest.param(
            {0: 10, 1: 70}, {0: 40, 1: 70}, ["partition 0"], id="legacy_stops_before_a_partitions_first_offset"
        ),
        pytest.param(
            {0: 50}, {0: 40, 1: 5}, ["partition 1 has no row in sharded_flag_evaluations"], id="partition_only_in_new"
        ),
        pytest.param(
            {0: 50, 1: 5},
            {0: 40},
            ["partition 1 has no row in sharded_flag_evaluations_json"],
            id="partition_only_in_legacy",
        ),
    ],
)
def test_cutover_problems_name_each_gap_between_the_two_consumer_groups(
    legacy: Mapping[int, int], new: Mapping[int, int], expected_fragments: list[str]
) -> None:
    problems = cutover_problems(legacy, new)

    assert len(problems) == len(expected_fragments)
    for problem, fragment in zip(problems, expected_fragments):
        assert fragment in problem


def test_compare_counts_lists_each_key_whose_count_differs() -> None:
    legacy = {("a",): 3, ("b",): 2, ("c",): 1}
    new = {("a",): 3, ("b",): 5, ("d",): 4}

    assert compare_counts(legacy, new) == [(("b",), 2, 5), (("c",), 1, 0), (("d",), 0, 4)]


def run_parity(cluster: ClickhouseCluster, now: datetime) -> dagster.ExecuteInProcessResult:
    config = {"config": {"start_date": str((now - timedelta(days=WINDOW_DAYS)).date()), "end_date": str(now.date())}}
    return flag_evaluations_json_parity_job.execute_in_process(
        run_config={"ops": {"compare_flag_evaluations_json_parity": config}},
        resources={"cluster": cluster},
        instance=dagster.DagsterInstance.ephemeral(),
        raise_on_error=False,
    )


@pytest.mark.django_db
def test_parity_passes_after_a_backfill_even_with_an_unmerged_duplicate(
    cluster: ClickhouseCluster, now: datetime
) -> None:
    seed_source_events(cluster, now, [RECENT])
    seed_legacy_row(cluster, now, RECENT)
    seed_cutover_rows(cluster, now)
    assert run_backfill(cluster, **window(now)).success
    # A second insert of the Kafka row stays an unmerged copy, so count() differs while uniqExact(uuid) does not.
    seed_json_kafka_row(cluster, now, KAFKA_ROW, partition=0, offset=40)

    assert run_parity(cluster, now).success


@pytest.mark.django_db
def test_parity_fails_and_names_the_day_when_the_new_table_lacks_a_call(
    cluster: ClickhouseCluster, now: datetime
) -> None:
    seed_legacy_row(cluster, now, RECENT)

    result = run_parity(cluster, now)

    [failure] = result.get_step_failure_events()
    assert failure.step_failure_data.error is not None
    assert str(RECENT_DAY(now)) in failure.step_failure_data.error.message
    assert RECENT.properties["$feature_flag"] in failure.step_failure_data.error.message
