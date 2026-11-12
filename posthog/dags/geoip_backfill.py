"""Stage GeoIP-enriched copies of events that ingestion wrote without GeoIP.

An ingestion pod that cannot open its MMDB keeps running and returns null for every lookup. The GeoIP
transformation then returns the event unchanged, so the event lands with no `$geoip_*` properties and no
`$set` / `$set_once` GeoIP keys. This job finds such events by the time ingestion wrote them, recomputes
the transformation with `geoip_enrichment`, and writes the fixed rows to a staging table per run. It never
writes to `sharded_events`; later jobs read the staging table.
"""

import json
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any, TypeVar

from django.conf import settings

import dagster
import pydantic
from clickhouse_driver import Client

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.query_tagging import DagsterTags
from posthog.clickhouse.table_engines import ReplacingMergeTree, ReplicationScheme
from posthog.dags.common import JobOwners, dagster_tags
from posthog.dags.common.shards import inserted_rows, on_shard_host, shard_workload, tagged
from posthog.dags.geoip_enrichment import GeoipEnrichment, GeoipLookup, MmdbGeoipLookup, geoip_enrichment
from posthog.dataclasses import frozen
from posthog.models.event.sql import EVENTS_DATA_TABLE

from products.cdp.backend.facade.api import teams_with_enabled_transformation

T = TypeVar("T")

OWNER_TAG = {"owner": JobOwners.TEAM_INGESTION.value}

PRODUCT = ProductKey.PIPELINE_TRANSFORMATIONS

GEOIP_TEMPLATE_ID = "template-geoip"

GIB = 1024**3

# The staging table name matches the "tmp_*" glob in posthog/clickhouse/hcl/exclude.hcl, so the schema
# convergence gate does not report it as drift.
STAGING_TABLE_PREFIX = "tmp_geoip_backfill_"

# A successful lookup writes every GeoIP key into `$set`, with null for the missing ones. An event that
# has neither the property nor the `$set` key therefore never went through a successful lookup.
_AFFECTED_EVENT_FILTER = """
    timestamp >= %(event_time_floor)s AND timestamp < %(event_time_ceiling)s
    AND _timestamp >= %(written_from)s AND _timestamp < %(written_until)s
    AND JSONExtractString(properties, '$ip') != ''
    AND NOT JSONHas(properties, '$geoip_country_code')
    AND NOT JSONHas(properties, '$set', '$geoip_country_code')
"""

_TEAM_FILTER = " AND team_id IN %(team_ids)s"


class IngestionWindowConfig(dagster.Config):
    start: str = pydantic.Field(description="First Kafka write time (`_timestamp`) to repair, ISO 8601, UTC.")
    end: str = pydantic.Field(description="Kafka write time (`_timestamp`) to stop at, exclusive, ISO 8601, UTC.")


class GeoipBackfillConfig(dagster.Config):
    windows: list[IngestionWindowConfig] = pydantic.Field(
        description="The times ingestion wrote events without GeoIP. One window per incident, lane and region."
    )
    team_ids: list[int] | None = pydantic.Field(
        default=None, description="Repair only these teams. Leave empty to repair every affected team."
    )
    max_event_age_days: int = pydantic.Field(
        default=7,
        ge=0,
        description=(
            "How far before a window an event's own timestamp may be. Late mobile events can be days old. "
            "Historical imports can be years old, so raise this and pass team_ids for the historical lane."
        ),
    )
    mmdb_path: str = pydantic.Field(
        default=str(Path(settings.GEOIP_PATH) / "GeoLite2-City.mmdb"),
        description="The MMDB file to look up addresses in. Use the file ingestion used during the windows.",
    )
    team_chunk_size: int = pydantic.Field(default=50, ge=1, description="Teams per read.")
    slice_minutes: int = pydantic.Field(default=5, ge=1, description="Minutes of `_timestamp` per read.")
    max_rows_per_read: int = pydantic.Field(
        default=20_000,
        ge=1,
        description="A read that returns more rows splits its time slice in half and reads again.",
    )
    max_execution_time_seconds: int = pydantic.Field(default=10 * 60, description="ClickHouse max_execution_time.")
    max_memory_usage_bytes: int = pydantic.Field(default=16 * GIB, description="ClickHouse max_memory_usage.")


@frozen
class IngestionWindow:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError(f"window start {self.start} is not before its end {self.end}")

    def slices(self, minutes: int) -> Iterator["IngestionWindow"]:
        step = timedelta(minutes=minutes)
        start = self.start
        while start < self.end:
            end = min(start + step, self.end)
            yield IngestionWindow(start=start, end=end)
            start = end

    @property
    def can_split(self) -> bool:
        return self.end - self.start >= timedelta(seconds=2)

    def halves(self) -> list["IngestionWindow"]:
        # `_timestamp` has whole seconds, so the halves stay on whole seconds too.
        middle = self.start + timedelta(seconds=(self.end - self.start).total_seconds() // 2)
        return [IngestionWindow(start=self.start, end=middle), IngestionWindow(start=middle, end=self.end)]


@frozen
class StagingPlan:
    windows: tuple[IngestionWindow, ...]
    config: GeoipBackfillConfig

    def query_args(self, window: IngestionWindow) -> dict[str, Any]:
        return {
            "event_time_floor": _clickhouse_time(window.start - timedelta(days=self.config.max_event_age_days)),
            # Ingestion accepts timestamps up to a day ahead of the time it receives the event.
            "event_time_ceiling": _clickhouse_time(window.end + timedelta(days=1)),
            "written_from": _clickhouse_time(window.start),
            "written_until": _clickhouse_time(window.end),
        }


def _clickhouse_time(value: datetime) -> str:
    return f"{value.astimezone(UTC):%Y-%m-%d %H:%M:%S}"


@frozen
class EventColumn:
    name: str
    type: str

    @property
    def quoted(self) -> str:
        return f"`{self.name}`"


@frozen
class GeoipStagingTable:
    """The enriched rows of one run, on each shard of the events cluster.

    The table holds the plain (no DEFAULT, no MATERIALIZED) columns of `sharded_events` under the same
    sort key and version column, so a row and its original collapse in a ReplacingMergeTree. Two extra
    columns keep the original JSON for a rollback.
    """

    id: uuid.UUID

    @property
    def name(self) -> str:
        return f"{STAGING_TABLE_PREFIX}{self.id.hex}"

    @property
    def qualified_name(self) -> str:
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    def create(self, client: Client, columns: Sequence[EventColumn]) -> None:
        column_sql = ",\n".join(f"{column.quoted} {column.type}" for column in columns)
        engine = ReplacingMergeTree(self.name, ver="_timestamp", replication_scheme=ReplicationScheme.SHARDED)
        client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.qualified_name} (
                {column_sql},
                original_properties String,
                original_person_properties String
            )
            ENGINE = {engine}
            PARTITION BY toYYYYMM(timestamp)
            ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))
            """
        )

    def exists(self, client: Client) -> bool:
        [[count]] = client.execute(
            "SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        return count > 0

    def columns(self, client: Client) -> list[EventColumn]:
        """The event columns of the table, without the two rollback columns."""
        return [
            column
            for column in read_columns(client, self.name, plain_only=False)
            if column.name not in ("original_properties", "original_person_properties")
        ]

    def drop(self, client: Client) -> None:
        client.execute(f"DROP TABLE IF EXISTS {self.qualified_name} SYNC")

    def sync(self, client: Client) -> None:
        client.execute(f"SYSTEM SYNC REPLICA {self.qualified_name} STRICT")


def read_columns(client: Client, table: str, *, plain_only: bool) -> list[EventColumn]:
    # A DEFAULT or MATERIALIZED column is left out so that the target computes it from the enriched
    # properties, the same way it does for a row from Kafka.
    kind_filter = " AND default_kind = ''" if plain_only else ""
    rows = client.execute(
        f"""
        SELECT name, type FROM system.columns
        WHERE database = %(database)s AND table = %(table)s{kind_filter}
        ORDER BY position
        """,
        {"database": settings.CLICKHOUSE_DATABASE, "table": table},
    )
    return [EventColumn(name=name, type=column_type) for name, column_type in rows]


@frozen
class TeamCount:
    team_id: int
    count: int


def team_counts(rows: Sequence[Sequence[int]]) -> list[TeamCount]:
    """Rows of `SELECT team_id, count()`."""
    return [TeamCount(team_id=team_id, count=count) for team_id, count in rows]


@frozen
class AffectedTeams:
    team_ids: tuple[int, ...]


@frozen
class ShardStagingTotals:
    read: int
    staged: int
    no_match: int


def plan_windows(config: GeoipBackfillConfig, now: datetime) -> tuple[IngestionWindow, ...]:
    if not config.windows:
        raise dagster.Failure(description="Give at least one window.")
    windows = []
    for window in config.windows:
        start = _parse_utc(window.start)
        end = _parse_utc(window.end)
        if start >= end:
            raise dagster.Failure(description=f"Window {window.start} to {window.end} does not move forward.")
        if end > now:
            raise dagster.Failure(description=f"Window {window.start} to {window.end} ends in the future.")
        windows.append(IngestionWindow(start=start, end=end))
    return tuple(sorted(windows, key=lambda window: window.start))


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value).replace(microsecond=0)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def enrich_row(
    row: Mapping[str, Any], lookup: GeoipLookup, staged_at: datetime
) -> tuple[dict[str, Any], GeoipEnrichment] | None:
    """The staged copy of an events row, or None when the transformation would leave the event unchanged."""
    properties = _json_object(row["properties"])
    enrichment = geoip_enrichment(properties, lookup)
    if enrichment is None:
        return None
    staged = dict(row)
    staged["properties"] = _dump(enrichment.apply(properties))
    staged["person_properties"] = _dump(enriched_person_properties(row, enrichment))
    staged["_timestamp"] = staged_at
    staged["original_properties"] = row["properties"]
    staged["original_person_properties"] = row["person_properties"]
    return staged, enrichment


def enriched_person_properties(row: Mapping[str, Any], enrichment: GeoipEnrichment) -> dict[str, Any]:
    """The person properties ingestion would have written on the event, after the event's own `$set_once`.

    A personless event carries no person properties, so it stays empty.
    """
    person_properties = _json_object(row["person_properties"])
    if row.get("person_mode") == "propertyless" or not person_properties:
        return person_properties
    person_properties.update(enrichment.set_properties)
    for key, value in enrichment.set_once_properties.items():
        person_properties.setdefault(key, value)
    return person_properties


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if value else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dump(value: Mapping[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _chunks(items: Sequence[int], size: int) -> Iterator[tuple[int, ...]]:
    for start in range(0, len(items), size):
        yield tuple(items[start : start + size])


@dagster.op(tags=OWNER_TAG)
def plan_geoip_backfill(context: dagster.OpExecutionContext, config: GeoipBackfillConfig) -> StagingPlan:
    windows = plan_windows(config, datetime.now(UTC))
    if not Path(config.mmdb_path).is_file():
        raise dagster.Failure(description=f"No MMDB at {config.mmdb_path}.")
    for window in windows:
        context.log.info(f"Window {window.start.isoformat()} to {window.end.isoformat()}")
    return StagingPlan(windows=windows, config=config)


@dagster.op(tags=OWNER_TAG)
def find_affected_teams(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    plan: StagingPlan,
) -> AffectedTeams:
    """Count the events without GeoIP per team, and keep the teams that run the GeoIP transformation.

    A team without the transformation never had GeoIP, so its events are not damaged. A team with
    `anonymize_ips` has no `$ip` on its events, so it never matches the filter.
    """
    team_filter = _TEAM_FILTER if plan.config.team_ids else ""
    query = f"SELECT team_id, count() FROM {EVENTS_DATA_TABLE()} WHERE {_AFFECTED_EVENT_FILTER}{team_filter} GROUP BY team_id"
    workload, node_role = shard_workload()
    query_tags = dagster_tags(context)
    counts: Counter[int] = Counter()
    for window in plan.windows:
        args = {**plan.query_args(window), "team_ids": tuple(plan.config.team_ids or ())}

        def count_teams(client: Client, args: dict[str, Any] = args) -> list[TeamCount]:
            return team_counts(
                sync_execute(
                    query,
                    args,
                    settings=_read_settings(plan.config),
                    workload=workload,
                    sync_client=client,
                    flush=False,
                )
            )

        per_shard = cluster.map_any_host_in_shards_by_role(
            {shard_num: tagged(query_tags, count_teams, product=PRODUCT) for shard_num in cluster.shards},
            workload=workload,
            node_role=node_role,
        ).result()
        for shard_counts in per_shard.values():
            for team_count in shard_counts:
                counts[team_count.team_id] += team_count.count

    with_geoip = teams_with_enabled_transformation(template_id=GEOIP_TEMPLATE_ID, team_ids=counts.keys())
    affected = Counter({team_id: events for team_id, events in counts.items() if team_id in with_geoip})
    skipped = {team_id: events for team_id, events in counts.items() if team_id not in with_geoip}
    context.log.info(
        f"{len(affected)} team(s) with {sum(affected.values())} event(s) to repair. "
        f"Skipped {len(skipped)} team(s) without the GeoIP transformation ({sum(skipped.values())} event(s))."
    )
    context.add_output_metadata(
        {
            "teams": dagster.MetadataValue.int(len(affected)),
            "events": dagster.MetadataValue.int(sum(affected.values())),
            "skipped_teams": dagster.MetadataValue.int(len(skipped)),
            "skipped_events": dagster.MetadataValue.int(sum(skipped.values())),
            "events_per_team": dagster.MetadataValue.json({str(team): n for team, n in affected.most_common(500)}),
        }
    )
    return AffectedTeams(team_ids=tuple(sorted(affected)))


def _read_settings(config: GeoipBackfillConfig) -> dict[str, Any]:
    return {
        "max_execution_time": config.max_execution_time_seconds,
        "max_memory_usage": config.max_memory_usage_bytes,
    }


@dagster.op(tags=OWNER_TAG)
def create_staging_table(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    teams: AffectedTeams,
) -> GeoipStagingTable:
    table = GeoipStagingTable(id=uuid.UUID(context.run.run_id))
    columns = cluster.any_host_by_role(
        partial(read_columns, table=EVENTS_DATA_TABLE(), plain_only=True), NodeRole.DATA
    ).result()
    cluster.map_hosts_by_role(partial(table.create, columns=columns), NodeRole.DATA).result()
    context.log.info(f"Created {table.qualified_name} for {len(teams.team_ids)} team(s)")
    return table


@dagster.op(out=dagster.DynamicOut(int), tags=OWNER_TAG)
def get_staging_shards(
    cluster: dagster.ResourceParam[ClickhouseCluster], table: GeoipStagingTable
) -> Iterator[dagster.DynamicOutput[int]]:
    """Fan out one op per shard, so a failed shard can be re-executed on its own from the UI."""
    for shard_num in sorted(cluster.shards):
        yield dagster.DynamicOutput(shard_num, mapping_key=f"shard_{shard_num}")


@frozen
class ShardStaging:
    """Read one shard's affected rows, enrich them, and insert them into the staging table on the same shard.

    `sharded_events` and the staging table share the shard key, so reads and writes stay on the shard.
    A re-run inserts the same rows again with a newer `_timestamp`, which the table collapses.
    """

    cluster: ClickhouseCluster
    shard_num: int
    plan: StagingPlan
    table: GeoipStagingTable
    lookup: GeoipLookup
    staged_at: datetime
    log: dagster.DagsterLogManager
    query_tags: DagsterTags
    workload: Workload
    node_role: NodeRole

    def run(self, team_ids: Sequence[int]) -> ShardStagingTotals:
        columns = self._on_shard(self.table.columns)
        totals = ShardStagingTotals(read=0, staged=0, no_match=0)
        for window in self.plan.windows:
            for chunk in _chunks(team_ids, self.plan.config.team_chunk_size):
                for time_slice in window.slices(self.plan.config.slice_minutes):
                    totals = self._add(totals, self._stage_slice(columns, chunk, time_slice))
        return totals

    def _stage_slice(
        self, columns: Sequence[EventColumn], team_ids: tuple[int, ...], time_slice: IngestionWindow
    ) -> ShardStagingTotals:
        rows = self._read(columns, team_ids, time_slice)
        if rows is None:
            totals = ShardStagingTotals(read=0, staged=0, no_match=0)
            for half in time_slice.halves():
                totals = self._add(totals, self._stage_slice(columns, team_ids, half))
            return totals
        staged = []
        for row in rows:
            enriched = enrich_row(row, self.lookup, self.staged_at)
            if enriched is not None:
                staged.append(enriched[0])
        if staged:
            self._insert(columns, staged)
        self.log.info(
            f"Shard {self.shard_num}, {time_slice.start.isoformat()} to {time_slice.end.isoformat()}, "
            f"{len(team_ids)} team(s): read {len(rows)}, staged {len(staged)}"
        )
        return ShardStagingTotals(read=len(rows), staged=len(staged), no_match=len(rows) - len(staged))

    def _read(
        self, columns: Sequence[EventColumn], team_ids: tuple[int, ...], time_slice: IngestionWindow
    ) -> list[dict[str, Any]] | None:
        """The slice's rows, or None when it holds more than max_rows_per_read and can still be split."""
        limit = self.plan.config.max_rows_per_read
        can_split = time_slice.can_split
        query = f"""
            SELECT {", ".join(column.quoted for column in columns)}
            FROM {EVENTS_DATA_TABLE()}
            WHERE {_AFFECTED_EVENT_FILTER}{_TEAM_FILTER}
            {"LIMIT %(limit)s" if can_split else ""}
        """
        args = {**self.plan.query_args(time_slice), "team_ids": team_ids, "limit": limit + 1}

        def read(client: Client) -> list[tuple[Any, ...]]:
            return sync_execute(
                query,
                args,
                settings=_read_settings(self.plan.config),
                workload=self.workload,
                sync_client=client,
                flush=False,
            )

        rows = self._on_shard(read)
        if can_split and len(rows) > limit:
            return None
        names = [column.name for column in columns]
        return [dict(zip(names, row)) for row in rows]

    def _insert(self, columns: Sequence[EventColumn], rows: Sequence[Mapping[str, Any]]) -> None:
        names = [*(column.name for column in columns), "original_properties", "original_person_properties"]
        query = f"INSERT INTO {self.table.qualified_name} ({', '.join(f'`{name}`' for name in names)}) VALUES"
        values = [tuple(row[name] for name in names) for row in rows]

        def insert(client: Client) -> int:
            return inserted_rows(sync_execute(query, values, workload=self.workload, sync_client=client, flush=False))

        self._on_shard(insert)

    @staticmethod
    def _add(first: ShardStagingTotals, second: ShardStagingTotals) -> ShardStagingTotals:
        return ShardStagingTotals(
            read=first.read + second.read,
            staged=first.staged + second.staged,
            no_match=first.no_match + second.no_match,
        )

    def _on_shard(self, fn: Callable[[Client], T]) -> T:
        return on_shard_host(
            self.cluster, self.shard_num, fn, self.query_tags, self.workload, self.node_role, product=PRODUCT
        )


def open_lookup(path: str) -> MmdbGeoipLookup:
    return MmdbGeoipLookup(Path(path))


@dagster.op(tags=OWNER_TAG)
def stage_shard(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    shard_num: int,
    plan: StagingPlan,
    teams: AffectedTeams,
    table: GeoipStagingTable,
) -> int:
    workload, node_role = shard_workload()
    lookup = open_lookup(plan.config.mmdb_path)
    try:
        totals = ShardStaging(
            cluster=cluster,
            shard_num=shard_num,
            plan=plan,
            table=table,
            lookup=lookup,
            staged_at=datetime.now(UTC),
            log=context.log,
            query_tags=dagster_tags(context),
            workload=workload,
            node_role=node_role,
        ).run(teams.team_ids)
    finally:
        lookup.close()
    context.add_output_metadata(
        {
            "shard": dagster.MetadataValue.int(shard_num),
            "read": dagster.MetadataValue.int(totals.read),
            "staged": dagster.MetadataValue.int(totals.staged),
            "no_match": dagster.MetadataValue.int(totals.no_match),
            "mmdb_build_epoch": dagster.MetadataValue.int(lookup.build_epoch),
        }
    )
    return totals.staged


@dagster.op(tags=OWNER_TAG)
def report_staging(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table: GeoipStagingTable,
    staged_shards: list[int],
) -> GeoipStagingTable:
    """Report the staged rows per team, once every replica holds every insert."""
    cluster.map_hosts_by_role(table.sync, NodeRole.DATA).result()

    def per_team(client: Client) -> list[TeamCount]:
        return team_counts(
            client.execute(f"SELECT team_id, count() FROM {table.qualified_name} FINAL GROUP BY team_id")
        )

    counts: Counter[int] = Counter()
    for shard_counts in cluster.map_one_host_per_shard(per_team).result().values():
        for team_count in shard_counts:
            counts[team_count.team_id] += team_count.count
    context.add_output_metadata(
        {
            "table": dagster.MetadataValue.text(table.qualified_name),
            "rows": dagster.MetadataValue.int(sum(counts.values())),
            "teams": dagster.MetadataValue.int(len(counts)),
            "rows_per_team": dagster.MetadataValue.json({str(team): n for team, n in counts.most_common(500)}),
        }
    )
    context.log.info(
        f"{table.qualified_name} holds {sum(counts.values())} row(s) for {len(counts)} team(s). "
        f"Pass staging_run_id={table.id} to the resend and person repair jobs."
    )
    return table


@dagster.job(tags=OWNER_TAG)
def geoip_backfill_staging_job() -> None:
    """Write GeoIP-enriched copies of the events ingested without GeoIP to a staging table.

    The job changes no event. It keeps its staging table for the jobs that resend events and repair persons.
    Drop the table with cleanup_geoip_backfill_staging once the repair is done.
    """
    plan = plan_geoip_backfill()
    teams = find_affected_teams(plan)
    table = create_staging_table(teams)
    staged = get_staging_shards(table).map(lambda shard_num: stage_shard(shard_num, plan, teams, table))
    report_staging(table, staged.collect())


class StagingRunConfig(dagster.Config):
    staging_run_id: str = pydantic.Field(description="The ID of the geoip_backfill_staging_job run.")


@dagster.op(tags=OWNER_TAG)
def drop_staging_table(cluster: dagster.ResourceParam[ClickhouseCluster], config: StagingRunConfig) -> None:
    cluster.map_hosts_by_role(GeoipStagingTable(id=uuid.UUID(config.staging_run_id)).drop, NodeRole.DATA).result()


@dagster.job(tags=OWNER_TAG)
def cleanup_geoip_backfill_staging() -> None:
    """Drop the staging table of a geoip_backfill_staging_job run."""
    drop_staging_table()
