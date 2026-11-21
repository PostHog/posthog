from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any

from django.conf import settings

import dagster
import pydantic
from clickhouse_driver import Client
from clickhouse_driver.errors import ServerException

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.cluster import ClickhouseCluster, HostInfo, NodeRole
from posthog.clickhouse.events_json import EVENTS_JSON_INSERT_SETTINGS
from posthog.cloud_utils import is_cloud
from posthog.dags.common import JobOwners, dagster_tags
from posthog.dags.flag_evaluations_backfill import (
    COPIED_ROW_FILTER,
    BackfillGuardConfig,
    BackfillGuards,
    inserted_rows,
    shard_workload,
    tagged,
)
from posthog.dataclasses import frozen
from posthog.models.event.sql import (
    EVENTS_DATA_TABLE,
    EVENTS_JSON_CLEANED_ALIAS,
    EVENTS_JSON_CLEANER,
    EVENTS_PROPERTIES_JSON_TYPE,
    PERSON_PROPERTIES_JSON_TYPE,
    _cast_cleaned_properties,
    _cast_temporary_properties,
)
from posthog.models.flag_evaluations.sql import (
    FLAG_EVALUATIONS_DATA_TABLE,
    FLAG_EVALUATIONS_JSON_DATA_TABLE,
    FLAG_EVALUATIONS_PERSON_PROPERTIES_EXPR,
    FLAG_EVALUATIONS_SOURCE_EVENT,
    FLAG_EVALUATIONS_TTL_DAYS,
)

from products.feature_flags.backend.facade.flags import get_team_ids_in_flag_evaluations_only_organizations

_CLUSTER_DOESNT_EXIST = 701

OWNER_TAG = {"owner": JobOwners.TEAM_FEATURE_FLAGS.value}

# The oldest day that the job copies. A day dated D expires when day D + FLAG_EVALUATIONS_TTL_DAYS starts, so
# the three days left over give a run time to reach it.
_EARLIEST_START_DAYS_AGO = 89

# The cluster that holds every shard of sharded_events. A flags host reads one shard of it through cluster().
SOURCE_EVENTS_CLUSTER = "posthog_primary_replica"

_PIPELINE_SOURCE_COLUMNS = (
    "uuid, event, properties, timestamp, team_id, distinct_id, created_at, person_id, person_properties, "
    "person_created_at, person_mode, _timestamp"
)

# The columns that the copy writes. flag_key, response and request_id are left out so the shard computes them the
# same way it does for rows from Kafka. inserted_at is left out so its DEFAULT stamps the event timestamp, which
# keeps every copied row inside the deletion sweep's `inserted_at <= request.created_at` bound. _partition and
# _offset are left out so both are 0 on a copied row, which tells it apart from a row that came through Kafka.
_COPIED_COLUMNS = (
    "uuid, event, properties, temporary_properties, properties_null_keys, temporary_properties_null_keys, "
    "timestamp, team_id, distinct_id, created_at, _timestamp, person_id, person_properties, "
    "person_properties_null_keys, person_created_at, person_mode, captured_at, total_event_size"
)

# Both tables number partitions and offsets the same way, because they read the same topic. A copied row has
# offset 0 in partition 0, and so does the first message of that partition, which this filter therefore skips too.
_KAFKA_ROW_FILTER = "NOT (_partition = 0 AND _offset = 0)"


class FlagEvaluationsJsonBackfillConfig(BackfillGuardConfig):
    start_date: str | None = pydantic.Field(
        default=None,
        description=(
            f"First day to copy (YYYY-MM-DD, UTC, inclusive). Defaults to {_EARLIEST_START_DAYS_AGO} days "
            "before today, which is also the earliest allowed value."
        ),
    )
    end_date: str | None = pydantic.Field(
        default=None,
        description=(
            "Day after the last day to copy (YYYY-MM-DD, UTC, exclusive). Defaults to tomorrow, so the run "
            "includes today, the day that dual-write starts."
        ),
    )
    team_ids: list[int] | None = pydantic.Field(
        default=None, description="Copy only these teams. Leave empty to copy every team."
    )
    flag_evaluations_team_ids: list[int] = pydantic.Field(
        default_factory=list,
        description=(
            "Teams to copy from flag_evaluations as well as from events, on top of the teams of every organization "
            "now on mode 2. Add the teams of an organization that moved to mode 2 and then back, because events "
            "lacks its calls from the days it spent on mode 2."
        ),
    )
    dry_run: bool = pydantic.Field(
        default=False,
        description="Count the rows each unit would copy instead of inserting them. The checks before each unit still run.",
    )
    source_cluster: str = pydantic.Field(default=SOURCE_EVENTS_CLUSTER, description="The cluster of sharded_events.")


@frozen
class CopyUnit:
    """One insert: a day of one source, either one shard of events or the whole flag_evaluations table."""

    day: date
    # None reads flag_evaluations.
    events_shard: int | None


@frozen
class JsonBackfillPlan:
    # Newest day first, so a run that stops partway leaves contiguous recent history. Within a day the events
    # shards come first and flag_evaluations last, so the anti-join of the last insert sees the rows of the others.
    units: tuple[CopyUnit, ...]
    flag_evaluations_team_ids: tuple[int, ...]
    config: FlagEvaluationsJsonBackfillConfig


def resolve_days(*, start_date: str | None = None, end_date: str | None = None, today: date) -> tuple[date, ...]:
    earliest_start = today - timedelta(days=_EARLIEST_START_DAYS_AGO)
    latest_end = today + timedelta(days=1)
    start = date.fromisoformat(start_date) if start_date else earliest_start
    end = date.fromisoformat(end_date) if end_date else latest_end
    if start < earliest_start:
        raise dagster.Failure(
            description=f"start_date {start} is before {earliest_start}, which the {FLAG_EVALUATIONS_TTL_DAYS}-day "
            "TTL leaves a run three days to reach."
        )
    if end > latest_end:
        raise dagster.Failure(description=f"end_date {end} is after tomorrow ({latest_end}).")
    if start >= end:
        raise dagster.Failure(description=f"start_date {start} must be before end_date {end}.")
    return tuple(end - timedelta(days=offset) for offset in range(1, (end - start).days + 1))


def is_expired(day: date, today: date) -> bool:
    return day + timedelta(days=FLAG_EVALUATIONS_TTL_DAYS) <= today


def plan_units(
    days: Sequence[date], source_shards: Sequence[int], flag_evaluations_team_ids: Sequence[int]
) -> tuple[CopyUnit, ...]:
    units: list[CopyUnit] = []
    for day in days:
        units.extend(CopyUnit(day=day, events_shard=shard) for shard in sorted(source_shards))
        if flag_evaluations_team_ids:
            units.append(CopyUnit(day=day, events_shard=None))
    return tuple(units)


def cutover_problems(legacy_last_offsets: Mapping[int, int], json_first_offsets: Mapping[int, int]) -> list[str]:
    """Return why the copy cannot run yet. An empty list means every message before the new table's first
    Kafka row is in the legacy table.

    A message that the legacy consumer group has not read, and that precedes the first message of the new group,
    lands in neither table. The legacy table holds a message at offset N of a partition only when its group
    consumed that far, so its last offset has to reach the new group's first offset on every partition.
    """
    if not json_first_offsets:
        return [f"{FLAG_EVALUATIONS_JSON_DATA_TABLE} has no row from Kafka, so its first offsets are unknown"]
    if not legacy_last_offsets:
        return [f"{FLAG_EVALUATIONS_DATA_TABLE} has no row from Kafka, so its last offsets are unknown"]
    problems = []
    for partition in sorted({*legacy_last_offsets, *json_first_offsets}):
        if partition not in json_first_offsets:
            problems.append(f"partition {partition} has no row in {FLAG_EVALUATIONS_JSON_DATA_TABLE}")
        elif partition not in legacy_last_offsets:
            problems.append(f"partition {partition} has no row in {FLAG_EVALUATIONS_DATA_TABLE}")
        elif legacy_last_offsets[partition] < json_first_offsets[partition]:
            problems.append(
                f"partition {partition}: {FLAG_EVALUATIONS_DATA_TABLE} ends at offset "
                f"{legacy_last_offsets[partition]}, before {FLAG_EVALUATIONS_JSON_DATA_TABLE} starts at "
                f"{json_first_offsets[partition]}"
            )
    return problems


def build_copy_query(*, events_shard: int | None, dry_run: bool, filter_team_ids: bool) -> str:
    """Build the insert of one unit.

    The inner query only filters and returns raw columns. It is the part that runs on the events shard. The
    cleaner, the casts and the anti-join run in the outer query, on the flags host that writes.
    """
    team_filter = " AND team_id IN %(team_ids)s" if filter_team_ids else ""
    day_filter = "timestamp >= %(day_start)s AND timestamp < %(day_end)s"
    if events_shard is None:
        source = f"""
SELECT {_PIPELINE_SOURCE_COLUMNS}
FROM {FLAG_EVALUATIONS_DATA_TABLE}
WHERE {day_filter} AND team_id IN %(flag_evaluations_team_ids)s{team_filter}
"""
    else:
        # The fork's eligibility rule: a non-empty string $feature_flag.
        source = f"""
SELECT {_PIPELINE_SOURCE_COLUMNS}
FROM cluster(%(source_cluster)s, {settings.CLICKHOUSE_DATABASE}, {EVENTS_DATA_TABLE()})
WHERE _shard_num = %(events_shard)s AND event = %(event)s AND {day_filter}{team_filter}
    AND JSONType(properties, '$feature_flag') = 'String'
    AND JSONExtractString(properties, '$feature_flag') != ''
"""
    # A LEFT ANTI JOIN keeps the lookup in the target table on this host. A `uuid NOT IN (subquery)` filter
    # gets pushed into the remote read, where the events shard looks for the table in its own database.
    cleaned = f"""
SELECT source.*, {EVENTS_JSON_CLEANER}(source.properties, {FLAG_EVALUATIONS_PERSON_PROPERTIES_EXPR}) AS {EVENTS_JSON_CLEANED_ALIAS}
FROM ({source}) AS source
LEFT ANTI JOIN (
    SELECT uuid FROM {FLAG_EVALUATIONS_JSON_DATA_TABLE} WHERE {day_filter}{team_filter}
) AS existing ON source.uuid = existing.uuid
"""
    if dry_run:
        return f"SELECT count() FROM ({cleaned})"
    cleaned_alias = EVENTS_JSON_CLEANED_ALIAS
    return f"""
INSERT INTO {FLAG_EVALUATIONS_JSON_DATA_TABLE} ({_COPIED_COLUMNS})
SELECT
    *,
    accurateCast(byteSize(*) + byteSize(toUInt32(0)), 'UInt32') AS total_event_size
FROM (
    SELECT
        uuid,
        event,
        {_cast_cleaned_properties("properties", "source.properties", EVENTS_PROPERTIES_JSON_TYPE())} AS properties,
        {_cast_temporary_properties("temporary_properties")} AS temporary_properties,
        {cleaned_alias}.properties_null_keys AS properties_null_keys,
        {cleaned_alias}.temporary_properties_null_keys AS temporary_properties_null_keys,
        timestamp,
        team_id,
        distinct_id,
        created_at,
        _timestamp,
        person_id,
        {_cast_cleaned_properties("person_properties", "source.person_properties", PERSON_PROPERTIES_JSON_TYPE())} AS person_properties,
        {cleaned_alias}.person_properties_null_keys AS person_properties_null_keys,
        person_created_at,
        person_mode,
        created_at AS captured_at
    FROM ({cleaned}) AS source
)
SETTINGS {EVENTS_JSON_INSERT_SETTINGS}
"""


@frozen
class UnitBackfill(BackfillGuards):
    """Copy one unit into sharded_flag_evaluations_json on a flags host.

    The flags cluster has one shard, so the guards run on that shard. The copy reads an events shard remotely
    and flag_evaluations locally, and writes locally.
    """

    config: FlagEvaluationsJsonBackfillConfig
    flag_evaluations_team_ids: tuple[int, ...]
    target_table: str = FLAG_EVALUATIONS_JSON_DATA_TABLE
    job_name: str = "flag_evaluations_json_backfill_job"

    def undo_instructions(self, day: date) -> str:
        # A rerun for the same teams does not copy back the rows that earlier runs copied for other teams.
        team_filter = f" AND team_id IN ({', '.join(map(str, self.config.team_ids))})" if self.config.team_ids else ""
        return (
            f"The copy can hold rows that the run removed from {FLAG_EVALUATIONS_DATA_TABLE} or {EVENTS_DATA_TABLE()}. "
            f"After that run finishes, delete the rows this job copied for {day} "
            f"(`DELETE FROM {FLAG_EVALUATIONS_JSON_DATA_TABLE} WHERE toDate(timestamp) = '{day}' "
            f"AND {COPIED_ROW_FILTER}{team_filter}`), then run the backfill again for the same teams."
        )

    def run(self, unit: CopyUnit) -> int:
        today = datetime.now(UTC).date()
        if is_expired(unit.day, today):
            self.log.warning(f"Skipping {unit.day}: the TTL has already expired it.")
            return 0
        if not self.config.dry_run:
            self.check_no_other_backfill_run()
        copy_host = self.cluster.any_host_in_shard_by_roles(self.shard_num, [self.node_role], self.workload)
        self.wait_for_parts_to_merge(unit.day, copy_host)
        blocking_run_check = self._wait_for_disk_and_blocking_runs()
        try:
            rows = self._copy(unit, copy_host)
        finally:
            if not self.config.dry_run:
                self.check_no_blocking_run_started(blocking_run_check, day=unit.day)
        source = "flag_evaluations" if unit.events_shard is None else f"events shard {unit.events_shard}"
        action = "would copy" if self.config.dry_run else "copied"
        self.log.info(f"{unit.day}, {source}: {action} {rows} row(s) on {copy_host.connection_info.host}")
        return rows

    def _copy(self, unit: CopyUnit, copy_host: HostInfo) -> int:
        params = {
            "event": FLAG_EVALUATIONS_SOURCE_EVENT,
            "day_start": f"{unit.day:%Y-%m-%d} 00:00:00",
            "day_end": f"{unit.day + timedelta(days=1):%Y-%m-%d} 00:00:00",
            "source_cluster": self.config.source_cluster,
            "events_shard": unit.events_shard,
            "team_ids": tuple(self.config.team_ids or ()),
            "flag_evaluations_team_ids": self.flag_evaluations_team_ids,
        }
        query = build_copy_query(
            events_shard=unit.events_shard, dry_run=self.config.dry_run, filter_team_ids=bool(self.config.team_ids)
        )
        settings_ = {
            "max_execution_time": self.config.max_execution_time_seconds,
            "max_memory_usage": self.config.max_memory_usage_bytes,
            "max_insert_threads": self.config.max_insert_threads,
        }

        def run_query(client: Client) -> int:
            result = sync_execute(query, params, settings=settings_, workload=self.workload, sync_client=client)
            return result[0][0] if self.config.dry_run else inserted_rows(result)

        return self._on_host(copy_host, run_query)


def _read_offsets(table: str, aggregate: str, client: Client) -> dict[int, int]:
    rows = sync_execute(
        f"SELECT _partition, {aggregate}(_offset) FROM {table} WHERE {_KAFKA_ROW_FILTER} GROUP BY _partition",
        sync_client=client,
    )
    return dict(rows)


def _read_source_shards(source_cluster: str, client: Client) -> list[int]:
    return [
        row[0]
        for row in sync_execute(
            "SELECT DISTINCT shard_num FROM system.clusters WHERE cluster = %(cluster)s ORDER BY shard_num",
            {"cluster": source_cluster},
            sync_client=client,
        )
    ]


def _count_tables(client: Client) -> int:
    return sync_execute(
        "SELECT count() FROM system.tables WHERE database = currentDatabase() AND name IN %(names)s",
        {"names": (FLAG_EVALUATIONS_DATA_TABLE, FLAG_EVALUATIONS_JSON_DATA_TABLE)},
        sync_client=client,
    )[0][0]


def flags_cluster(cluster: ClickhouseCluster) -> tuple[ClickhouseCluster, Workload, NodeRole]:
    """The handle for the flags cluster, where sharded_flag_evaluations_json lives, with its workload and role.

    The cluster resource addresses the posthog cluster. A development stack has no flags cluster and holds the
    table on its one host.
    """
    try:
        return cluster.sibling(settings.CLICKHOUSE_FLAGS_CLUSTER, NodeRole.FLAGS), Workload.DEFAULT, NodeRole.FLAGS
    except ServerException as exc:
        if exc.code != _CLUSTER_DOESNT_EXIST or is_cloud():
            raise
        workload, node_role = shard_workload()
        return cluster, workload, node_role


@dagster.op(tags=OWNER_TAG)
def plan_flag_evaluations_json_backfill(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: FlagEvaluationsJsonBackfillConfig,
) -> JsonBackfillPlan:
    """Resolve the window and check the preconditions once."""
    flags, workload, node_role = flags_cluster(cluster)
    host = flags.any_host_in_shard_by_roles(min(flags.shards), [node_role], workload)
    query_tags = dagster_tags(context)

    def on_host(fn: Any) -> Any:
        return flags.on_host(host, tagged(query_tags, fn)).result()

    if on_host(_count_tables) != 2:
        raise dagster.Failure(
            description=f"{FLAG_EVALUATIONS_DATA_TABLE} and {FLAG_EVALUATIONS_JSON_DATA_TABLE} must both exist "
            f"on {host.connection_info.host}."
        )
    problems = cutover_problems(
        on_host(partial(_read_offsets, FLAG_EVALUATIONS_DATA_TABLE, "max")),
        on_host(partial(_read_offsets, FLAG_EVALUATIONS_JSON_DATA_TABLE, "min")),
    )
    if problems:
        raise dagster.Failure(
            description="Messages between the two consumer groups can be missing from both tables: "
            + "; ".join(problems)
            + ". Run the backfill after the legacy consumer group has passed every partition's first offset "
            f"in {FLAG_EVALUATIONS_JSON_DATA_TABLE}."
        )
    source_shards = on_host(partial(_read_source_shards, config.source_cluster))
    if not source_shards:
        raise dagster.Failure(description=f"Cluster {config.source_cluster} has no shards on this host.")
    days = resolve_days(start_date=config.start_date, end_date=config.end_date, today=datetime.now(UTC).date())
    flag_evaluations_team_ids = tuple(
        sorted({*get_team_ids_in_flag_evaluations_only_organizations(), *config.flag_evaluations_team_ids})
    )
    units = plan_units(days, source_shards, flag_evaluations_team_ids)
    context.log.info(
        f"Copying {len(days)} day(s) from {days[0]} back to {days[-1]}, newest first, in {len(units)} unit(s). "
        f"{len(flag_evaluations_team_ids)} team(s) also copy from flag_evaluations."
    )
    return JsonBackfillPlan(units=units, flag_evaluations_team_ids=flag_evaluations_team_ids, config=config)


# One op runs every unit in order and stops at the first failure. Separate ops would let the units after a failed
# one keep copying, and the flag_evaluations unit of a day has to run after the events units of that day.
@dagster.op(tags=OWNER_TAG)
def copy_flag_evaluations_json(
    context: dagster.OpExecutionContext, cluster: dagster.ResourceParam[ClickhouseCluster], plan: JsonBackfillPlan
) -> int:
    flags, workload, node_role = flags_cluster(cluster)
    backfill = UnitBackfill(
        cluster=flags,
        shard_num=min(flags.shards),
        config=plan.config,
        flag_evaluations_team_ids=plan.flag_evaluations_team_ids,
        instance=context.instance,
        run_id=context.run_id,
        log=context.log,
        query_tags=dagster_tags(context),
        workload=workload,
        node_role=node_role,
    )
    total_rows = sum(backfill.run(unit) for unit in plan.units)
    context.add_output_metadata(
        {
            "units": dagster.MetadataValue.int(len(plan.units)),
            "rows": dagster.MetadataValue.int(total_rows),
            "dry_run": dagster.MetadataValue.bool(plan.config.dry_run),
        }
    )
    return total_rows


@dagster.job(tags=OWNER_TAG)
def flag_evaluations_json_backfill_job() -> None:
    """Copy $feature_flag_called history into flag_evaluations_json, one insert per source shard and day.

    The days run newest first. Safe to re-run over the same window: the anti-join inserts only rows that are
    missing. A re-run does not rewrite a stored row. To copy a day again, first delete the rows that an earlier
    run copied (`_partition = 0 AND _offset = 0 AND inserted_at = timestamp`). A run that stops partway leaves
    the days it finished. Set start_date and end_date to resume.
    """
    copy_flag_evaluations_json(plan_flag_evaluations_json_backfill())


class FlagEvaluationsJsonParityConfig(dagster.Config):
    start_date: str | None = pydantic.Field(
        default=None, description="First day to compare (YYYY-MM-DD, UTC, inclusive). Defaults to 89 days ago."
    )
    end_date: str | None = pydantic.Field(
        default=None,
        description=(
            "Day after the last day to compare (YYYY-MM-DD, UTC, exclusive). Defaults to today, so the "
            "comparison covers only completed days."
        ),
    )
    max_listed_mismatches: int = pydantic.Field(
        default=50, description="How many mismatched days and flag keys the failure message lists."
    )


@frozen
class ParityMismatch:
    day: date
    flag_key: str | None
    response: str | None
    legacy_uuids: int
    json_uuids: int


def _parity_day_query(table: str) -> str:
    return f"""
SELECT toDate(timestamp) AS day, uniqExact(uuid)
FROM {table}
WHERE timestamp >= %(start)s AND timestamp < %(end)s
GROUP BY day
"""


def _parity_flag_query(table: str) -> str:
    return f"""
SELECT toDate(timestamp) AS day, flag_key, response, uniqExact(uuid)
FROM {table}
WHERE timestamp >= %(start)s AND timestamp < %(end)s
GROUP BY day, flag_key, response
"""


def compare_counts(legacy: Mapping[tuple, int], new: Mapping[tuple, int]) -> list[tuple[tuple, int, int]]:
    """Return each key whose count differs, as (key, legacy count, new count), keys sorted."""
    return [
        (key, legacy.get(key, 0), new.get(key, 0))
        for key in sorted({*legacy, *new})
        if legacy.get(key, 0) != new.get(key, 0)
    ]


def _read_counts(query: str, params: dict[str, str], client: Client) -> dict[tuple, int]:
    return {tuple(row[:-1]): row[-1] for row in sync_execute(query, params, sync_client=client)}


@dagster.op(tags=OWNER_TAG)
def compare_flag_evaluations_json_parity(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: FlagEvaluationsJsonParityConfig,
) -> int:
    """Compare the distinct uuids of each day, and of each day, flag_key and response, in both tables.

    The count is `uniqExact(uuid)`, never `count()`, because unmerged ReplacingMergeTree copies make the row
    counts differ. Fails when any count differs. Days before the legacy table's fork started differ by design,
    because that table lacks calls that events holds, so read the listed days against that date.
    """
    today = datetime.now(UTC).date()
    start = (
        date.fromisoformat(config.start_date) if config.start_date else today - timedelta(days=_EARLIEST_START_DAYS_AGO)
    )
    end = date.fromisoformat(config.end_date) if config.end_date else today
    if start >= end:
        raise dagster.Failure(description=f"start_date {start} must be before end_date {end}.")
    flags, workload, node_role = flags_cluster(cluster)
    host = flags.any_host_in_shard_by_roles(min(flags.shards), [node_role], workload)
    query_tags = dagster_tags(context)
    params = {"start": f"{start:%Y-%m-%d} 00:00:00", "end": f"{end:%Y-%m-%d} 00:00:00"}

    def counts(query: str) -> dict[tuple, int]:
        return flags.on_host(host, tagged(query_tags, partial(_read_counts, query, params))).result()

    day_diffs = compare_counts(
        counts(_parity_day_query(FLAG_EVALUATIONS_DATA_TABLE)),
        counts(_parity_day_query(FLAG_EVALUATIONS_JSON_DATA_TABLE)),
    )
    flag_diffs = compare_counts(
        counts(_parity_flag_query(FLAG_EVALUATIONS_DATA_TABLE)),
        counts(_parity_flag_query(FLAG_EVALUATIONS_JSON_DATA_TABLE)),
    )
    mismatches = [
        ParityMismatch(day=key[0], flag_key=None, response=None, legacy_uuids=a, json_uuids=b)
        for key, a, b in day_diffs
    ]
    mismatches += [
        ParityMismatch(day=key[0], flag_key=key[1], response=key[2], legacy_uuids=a, json_uuids=b)
        for key, a, b in flag_diffs
    ]
    context.add_output_metadata(
        {
            "start": dagster.MetadataValue.text(str(start)),
            "end": dagster.MetadataValue.text(str(end)),
            "mismatched_days": dagster.MetadataValue.int(len(day_diffs)),
            "mismatched_flag_keys": dagster.MetadataValue.int(len(flag_diffs)),
        }
    )
    if mismatches:
        listed = "; ".join(
            f"{m.day} {m.flag_key if m.flag_key is not None else 'all'} {m.response or ''}: "
            f"{m.legacy_uuids} in {FLAG_EVALUATIONS_DATA_TABLE}, {m.json_uuids} in {FLAG_EVALUATIONS_JSON_DATA_TABLE}"
            for m in mismatches[: config.max_listed_mismatches]
        )
        raise dagster.Failure(
            description=f"{len(day_diffs)} day(s) and {len(flag_diffs)} (day, flag_key, response) group(s) differ. "
            f"First {config.max_listed_mismatches}: {listed}"
        )
    return 0


@dagster.job(tags=OWNER_TAG)
def flag_evaluations_json_parity_job() -> None:
    """Compare flag_evaluations_json with flag_evaluations over completed days. Fails when any count differs."""
    compare_flag_evaluations_json_parity()
