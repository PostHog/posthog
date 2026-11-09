"""Stage GeoIP-enriched copies of events that ingestion wrote without GeoIP.

An ingestion pod that cannot open its MMDB keeps running and returns null for every lookup. The GeoIP
transformation then returns the event unchanged, so the event lands with no `$geoip_*` properties and no
`$set` / `$set_once` GeoIP keys. This job finds such events by the time ingestion wrote them, recomputes
the transformation with `geoip_enrichment`, and writes the fixed rows to a staging table per run. It never
writes to `sharded_events`; later jobs read the staging table.
"""

import re
import json
import math
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import partial
from json.encoder import encode_basestring
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
from posthog.dags.geoip_enrichment import (
    TEMPLATE_VERSIONS,
    GeoipEnrichment,
    GeoipLookup,
    GeoipTemplateVersion,
    MmdbGeoipLookup,
    geoip_enrichment,
    template_version,
)
from posthog.dataclasses import frozen
from posthog.models.dmat_slot_assignments.sql import DMAT_SLOT_ASSIGNMENTS_TABLE_NAME
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.team import Team

from products.cdp.backend.facade.api import EnabledTransformation, enabled_transformations

T = TypeVar("T")

OWNER_TAG = {"owner": JobOwners.TEAM_INGESTION.value}

PRODUCT = ProductKey.PIPELINE_TRANSFORMATIONS

GEOIP_TEMPLATE_ID = "template-geoip"
# Legacy plugins that look up the same MMDB. Their output differs from the template's, so the port
# cannot repair their events.
LEGACY_GEOIP_TEMPLATE_IDS = ("plugin-posthog-plugin-geoip", "plugin-plugin-advanced-geoip")

GIB = 1024**3

# The staging table name matches the "tmp_*" glob in posthog/clickhouse/hcl/exclude.hcl, so the schema
# convergence gate does not report it as drift.
STAGING_TABLE_PREFIX = "tmp_geoip_backfill_"

# A successful lookup writes every GeoIP key into `$set`, with null for the missing ones. An event that
# has neither the property nor the `$set` key therefore never went through a successful lookup.
_WRITTEN_WITHOUT_GEOIP_FILTER = """
    timestamp >= %(event_time_floor)s AND timestamp < %(event_time_ceiling)s
    AND _timestamp >= %(written_from)s AND _timestamp < %(written_until)s
    AND NOT JSONHas(properties, '$geoip_country_code')
    AND NOT JSONHas(properties, '$set', '$geoip_country_code')
"""
AFFECTED_EVENT_FILTER = _WRITTEN_WITHOUT_GEOIP_FILTER + "    AND JSONExtractString(properties, '$ip') != ''\n"
# ClickHouse cannot parse these properties, for example a lone surrogate escape, so the JSON functions in
# the filters above read nothing and the job never finds such an event.
_UNREADABLE_PROPERTIES_FILTER = """
    timestamp >= %(event_time_floor)s AND timestamp < %(event_time_ceiling)s
    AND _timestamp >= %(written_from)s AND _timestamp < %(written_until)s
    AND NOT isValidJSON(properties)
"""

_TEAM_FILTER = " AND team_id IN %(team_ids)s"

STAGING_EXTRA_COLUMNS = ("original_properties", "original_person_properties", "original_written_at")


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
    reviewed_team_ids: list[int] = pydantic.Field(
        default_factory=list,
        description=(
            "Repair these teams even when their GeoIP transformation has filters, an edited source, or a "
            "transformation after it. Check first that the port's output is what ingestion would have written."
        ),
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
        return window_query_args(window, self.config.max_event_age_days)


def window_query_args(window: IngestionWindow, max_event_age_days: int) -> dict[str, Any]:
    """The arguments of AFFECTED_EVENT_FILTER for one window."""
    return {
        "event_time_floor": _clickhouse_time(window.start - timedelta(days=max_event_age_days)),
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

    The table holds the plain (no DEFAULT, no MATERIALIZED) columns of `sharded_events` and `inserted_at`
    under the same sort key and version column, so a row and its original collapse in a
    ReplacingMergeTree. The extra columns keep the original JSON for a rollback, and the original
    `_timestamp`, which the staged copy replaces with the staging time.
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
                original_person_properties String,
                original_written_at DateTime
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
        """The event columns of the table, without the extra columns."""
        return [
            column
            for column in read_columns(client, self.name, plain_only=False)
            if column.name not in STAGING_EXTRA_COLUMNS
        ]

    def drop(self, client: Client) -> None:
        client.execute(f"DROP TABLE IF EXISTS {self.qualified_name} SYNC")

    def sync(self, client: Client) -> None:
        client.execute(f"SYSTEM SYNC REPLICA {self.qualified_name} STRICT")


# A DEFAULT column the copy keeps from its original. Deletions match on `inserted_at`, so a copy stamped
# with its own insert time would survive a deletion requested before the repair.
KEPT_DEFAULT_COLUMNS = ("inserted_at",)


def read_columns(client: Client, table: str, *, plain_only: bool) -> list[EventColumn]:
    # Any other DEFAULT or MATERIALIZED column is left out so that the target computes it from the
    # enriched properties, the same way it does for a row from Kafka.
    kept = ", ".join(f"'{name}'" for name in KEPT_DEFAULT_COLUMNS)
    kind_filter = f" AND (default_kind = '' OR name IN ({kept}))" if plain_only else ""
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
class RepairTeam:
    team_id: int
    version: GeoipTemplateVersion


@frozen
class AffectedTeams:
    teams: tuple[RepairTeam, ...]

    @property
    def team_ids(self) -> tuple[int, ...]:
        return tuple(team.team_id for team in self.teams)

    def versions(self) -> dict[int, GeoipTemplateVersion]:
        return {team.team_id: team.version for team in self.teams}


class Exclusion(StrEnum):
    """Why the job leaves out a team whose events lack GeoIP."""

    # Not damaged: the team runs no GeoIP lookup.
    NO_GEOIP = "no_geoip"
    # Damaged, but the port cannot say what ingestion would have written.
    LEGACY_GEOIP_PLUGIN = "legacy_geoip_plugin"
    FILTERS = "filters"
    EDITED_SOURCE = "edited_source"
    LATER_TRANSFORMATION = "later_transformation"
    # Damaged, but reads serve the team's GeoIP property from a dmat column, which the copy cannot change.
    MATERIALIZED_GEOIP = "materialized_geoip"


@frozen
class TeamDecision:
    version: GeoipTemplateVersion | None = None
    exclusion: Exclusion | None = None


def decide_team(transformations: Sequence[EnabledTransformation], *, reviewed: bool) -> TeamDecision:
    """Whether the port reproduces what ingestion would have written for a team with these transformations.

    `transformations` are the team's enabled transformations in the order ingestion runs them.
    """
    positions = [index for index, item in enumerate(transformations) if item.template_id == GEOIP_TEMPLATE_ID]
    if not positions:
        if any(item.template_id in LEGACY_GEOIP_TEMPLATE_IDS for item in transformations):
            return TeamDecision(exclusion=Exclusion.LEGACY_GEOIP_PLUGIN)
        return TeamDecision(exclusion=Exclusion.NO_GEOIP)
    geoip = transformations[positions[0]]
    version = template_version(geoip.hog)
    if reviewed:
        return TeamDecision(version=version or TEMPLATE_VERSIONS[-1])
    if geoip.has_filters:
        return TeamDecision(exclusion=Exclusion.FILTERS)
    if version is None:
        return TeamDecision(exclusion=Exclusion.EDITED_SOURCE)
    if positions[0] != len(transformations) - 1:
        # The stored event is the output of the later transformations, which saw no GeoIP keys.
        return TeamDecision(exclusion=Exclusion.LATER_TRANSFORMATION)
    return TeamDecision(version=version)


@frozen
class ShardStagingTotals:
    read: int
    staged: int
    no_match: int


def plan_windows(configs: Sequence[IngestionWindowConfig], now: datetime) -> tuple[IngestionWindow, ...]:
    if not configs:
        raise dagster.Failure(description="Give at least one window.")
    windows = []
    for window in configs:
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
    row: Mapping[str, Any], lookup: GeoipLookup, staged_at: datetime, version: GeoipTemplateVersion
) -> tuple[dict[str, Any], GeoipEnrichment] | None:
    """The staged copy of an events row, or None when the transformation would leave the event unchanged."""
    properties = _json_object(row["properties"])
    enrichment = geoip_enrichment(properties, lookup, version)
    if enrichment is None:
        return None
    staged = dict(row)
    staged["properties"] = node_json(enrichment.apply(properties))
    staged["person_properties"] = node_json(enriched_person_properties(row, enrichment))
    staged["_timestamp"] = staged_at
    staged["original_properties"] = row["properties"]
    staged["original_person_properties"] = row["person_properties"]
    staged["original_written_at"] = row["_timestamp"]
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


def node_json(value: Any) -> str:
    """JSON text as `JSON.stringify` writes it.

    Ingestion wrote the original text with `JSON.stringify`, so writing the same way keeps the bytes of
    every value the repair does not change. HogQL reads a property's raw text, so `1e-05` for the original
    `0.00001` would change what queries see.
    """
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _node_string(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _node_number(value)
    if isinstance(value, Mapping):
        return "{" + ",".join(f"{_node_string(str(key))}:{node_json(item)}" for key, item in value.items()) + "}"
    if isinstance(value, list | tuple):
        return "[" + ",".join(node_json(item) for item in value) + "]"
    raise TypeError(f"{type(value).__name__} is not JSON")


_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _node_string(value: str) -> str:
    # json.loads joins a valid surrogate pair into one character, so a surrogate left in the string is
    # alone. JSON.stringify escapes it. Written raw, it is not UTF-8, and the insert fails.
    text = encode_basestring(value)
    if _LONE_SURROGATE.search(text):
        text = _LONE_SURROGATE.sub(lambda match: f"\\u{ord(match.group()):04x}", text)
    return text


def _node_number(value: float) -> str:
    """Number::toString from the ECMAScript spec, on the shortest digits that repr() also picks."""
    if not math.isfinite(value):
        raise ValueError(f"{value} is not JSON")
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    mantissa, _, exponent = repr(abs(value)).partition("e")
    whole, _, fraction = mantissa.partition(".")
    digits = (whole + fraction).lstrip("0")
    # The value is 0.<digits> * 10**point.
    point = len(whole) + int(exponent or 0) - (len(whole + fraction) - len((whole + fraction).lstrip("0")))
    digits = digits.rstrip("0")
    count = len(digits)
    if count <= point <= 21:
        text = digits + "0" * (point - count)
    elif 0 < point <= 21:
        text = f"{digits[:point]}.{digits[point:]}"
    elif -6 < point <= 0:
        text = "0." + "0" * -point + digits
    else:
        written_exponent = point - 1
        text = digits[0] + (f".{digits[1:]}" if count > 1 else "")
        text += f"e{'+' if written_exponent >= 0 else '-'}{abs(written_exponent)}"
    return sign + text


def _chunks(items: Sequence[int], size: int) -> Iterator[tuple[int, ...]]:
    for start in range(0, len(items), size):
        yield tuple(items[start : start + size])


@dagster.op(tags=OWNER_TAG)
def plan_geoip_backfill(context: dagster.OpExecutionContext, config: GeoipBackfillConfig) -> StagingPlan:
    windows = plan_windows(config.windows, datetime.now(UTC))
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
    """Count the events without GeoIP per team, and keep the teams whose events the port can repair.

    A team without a GeoIP lookup never had GeoIP, so its events are not damaged. The op reports every
    other team it leaves out, with its events, because those events stay damaged:

    - a team on a legacy GeoIP plugin, a team whose GeoIP transformation has filters or an edited
      source, or one with a transformation after it, because the port cannot say what ingestion
      would have written (`reviewed_team_ids` includes such a team anyway)
    - a team that reads a GeoIP property from a dmat column, because the copy keeps the original's
      dmat values
    - a team with `anonymize_ips`, because ingestion deletes `$ip` after the transformations, so
      nothing is left to look up

    It also counts the events in the windows whose properties ClickHouse cannot parse, which no filter
    can match.
    """
    query_tags = dagster_tags(context)
    counts = _count_per_team(cluster, plan, query_tags, AFFECTED_EVENT_FILTER, plan.config.team_ids)
    transformations: defaultdict[int, list[EnabledTransformation]] = defaultdict(list)
    for transformation in enabled_transformations(team_ids=counts.keys()):
        transformations[transformation.team_id].append(transformation)
    reviewed = set(plan.config.reviewed_team_ids)
    decisions = {team_id: decide_team(transformations[team_id], reviewed=team_id in reviewed) for team_id in counts}
    for team_id in _teams_with_materialized_geoip(cluster, query_tags, [t for t, d in decisions.items() if d.version]):
        decisions[team_id] = TeamDecision(exclusion=Exclusion.MATERIALIZED_GEOIP)

    repair = {team_id: decision.version for team_id, decision in decisions.items() if decision.version}
    excluded: defaultdict[Exclusion, list[int]] = defaultdict(list)
    for team_id, decision in decisions.items():
        if decision.exclusion is not None:
            excluded[decision.exclusion].append(team_id)
    anonymized = _anonymized_teams_with_geoip(plan.config.team_ids)
    anonymized_counts = (
        _count_per_team(cluster, plan, query_tags, _WRITTEN_WITHOUT_GEOIP_FILTER, anonymized) if anonymized else {}
    )
    unreadable = _count_per_team(cluster, plan, query_tags, _UNREADABLE_PROPERTIES_FILTER, plan.config.team_ids)

    def events(team_ids: Collection[int], source: Mapping[int, int] = counts) -> int:
        return sum(source.get(team_id, 0) for team_id in team_ids)

    metadata: dict[str, Any] = {
        "teams": dagster.MetadataValue.int(len(repair)),
        "events": dagster.MetadataValue.int(events(repair)),
        "events_per_team": dagster.MetadataValue.json(
            dict(Counter({str(team_id): counts[team_id] for team_id in repair}).most_common(500))
        ),
        "anonymize_ips_teams": dagster.MetadataValue.int(len(anonymized_counts)),
        "anonymize_ips_events": dagster.MetadataValue.int(sum(anonymized_counts.values())),
        "unreadable_properties_events": dagster.MetadataValue.int(sum(unreadable.values())),
        "unreadable_properties_per_team": dagster.MetadataValue.json(
            {str(team_id): n for team_id, n in unreadable.most_common(100)}
        ),
    }
    context.log.info(f"{len(repair)} team(s) with {events(repair)} event(s) to repair.")
    for exclusion in Exclusion:
        team_ids = sorted(excluded[exclusion])
        metadata[f"{exclusion}_teams"] = dagster.MetadataValue.int(len(team_ids))
        metadata[f"{exclusion}_events"] = dagster.MetadataValue.int(events(team_ids))
        if exclusion != Exclusion.NO_GEOIP:
            metadata[f"{exclusion}_team_ids"] = dagster.MetadataValue.json(team_ids[:500])
        context.log.info(f"Left out {len(team_ids)} team(s) with {events(team_ids)} event(s): {exclusion}.")
    context.log.info(
        f"Left out {len(anonymized_counts)} team(s) with anonymize_ips and "
        f"{sum(anonymized_counts.values())} event(s) without GeoIP."
    )
    context.log.info(f"Left out {sum(unreadable.values())} event(s) whose properties ClickHouse cannot parse.")
    context.add_output_metadata(metadata)
    return AffectedTeams(
        teams=tuple(RepairTeam(team_id=team_id, version=version) for team_id, version in sorted(repair.items()))
    )


def _count_per_team(
    cluster: ClickhouseCluster,
    plan: StagingPlan,
    query_tags: DagsterTags,
    event_filter: str,
    team_ids: Collection[int] | None,
) -> Counter[int]:
    team_filter = _TEAM_FILTER if team_ids else ""
    query = f"SELECT team_id, count() FROM {EVENTS_DATA_TABLE()} WHERE {event_filter}{team_filter} GROUP BY team_id"
    workload, node_role = shard_workload()
    counts: Counter[int] = Counter()
    for window in plan.windows:
        args = {**plan.query_args(window), "team_ids": tuple(team_ids or ())}

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
    return counts


_MATERIALIZED_GEOIP_TEAMS_QUERY = f"""
    SELECT DISTINCT team_id FROM {DMAT_SLOT_ASSIGNMENTS_TABLE_NAME} FINAL
    WHERE team_id IN %(team_ids)s AND startsWith(property_name, '$geoip')
"""


def _teams_with_materialized_geoip(
    cluster: ClickhouseCluster, query_tags: DagsterTags, team_ids: Collection[int]
) -> set[int]:
    """The teams with a dmat slot for a GeoIP property. Every host holds the whole slot table."""
    if not team_ids:
        return set()
    workload, node_role = shard_workload()

    def read(client: Client) -> set[int]:
        rows = sync_execute(
            _MATERIALIZED_GEOIP_TEAMS_QUERY,
            {"team_ids": tuple(team_ids)},
            workload=workload,
            sync_client=client,
        )
        return {team_id for (team_id,) in rows}

    return cluster.any_host_by_role(tagged(query_tags, read, product=PRODUCT), node_role).result()


def _anonymized_teams_with_geoip(team_ids: Collection[int] | None) -> list[int]:
    teams = Team.objects.filter(anonymize_ips=True)
    if team_ids:
        teams = teams.filter(id__in=list(team_ids))
    geoip_template_ids = (GEOIP_TEMPLATE_ID, *LEGACY_GEOIP_TEMPLATE_IDS)
    return sorted(
        {
            transformation.team_id
            for transformation in enabled_transformations(team_ids=list(teams.values_list("id", flat=True)))
            if transformation.template_id in geoip_template_ids
        }
    )


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
    versions: Mapping[int, GeoipTemplateVersion]
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
            enriched = enrich_row(row, self.lookup, self.staged_at, self.versions[row["team_id"]])
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
            WHERE {AFFECTED_EVENT_FILTER}{_TEAM_FILTER}
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
        names = [*(column.name for column in columns), *STAGING_EXTRA_COLUMNS]
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
    lookup = MmdbGeoipLookup(Path(plan.config.mmdb_path))
    # The reader raises once it is closed, so read the build time first.
    build_epoch = lookup.build_epoch
    try:
        totals = ShardStaging(
            cluster=cluster,
            shard_num=shard_num,
            plan=plan,
            table=table,
            versions=teams.versions(),
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
            "mmdb_build_epoch": dagster.MetadataValue.int(build_epoch),
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
