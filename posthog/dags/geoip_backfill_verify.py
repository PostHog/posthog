"""Report how far the GeoIP backfill has repaired the events of a geoip_backfill_staging_job run.

The job only reads. For each staged team it counts, on every shard:

- `repaired`: staged events whose newest row in `sharded_events` has `$geoip_country_code`.
- `pending`: staged events whose newest row still has none. Equal to the staged count before a resend.
- `missing`: staged events with no row left in `sharded_events`, such as events a deletion removed.
- `duplicate_rows`: extra rows of staged events that a merge has not collapsed yet. A query without
  FINAL counts each of them as an event, so this is the double count the resend causes.
- `left_in_windows`: with `windows` set, events written in the windows whose newest row still has an
  `$ip` and no GeoIP. After a full resend, these are the addresses the MMDB has no record for.

"Newest" is the row with the highest `_timestamp`, the one the ReplacingMergeTree keeps in a merge.
"""

import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

import dagster
import pydantic
from clickhouse_driver import Client

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.query_tagging import DagsterTags
from posthog.dags.common import dagster_tags
from posthog.dags.common.shards import shard_workload, tagged
from posthog.dags.geoip_backfill import (
    AFFECTED_EVENT_FILTER,
    OWNER_TAG,
    PRODUCT,
    GeoipStagingTable,
    IngestionWindow,
    IngestionWindowConfig,
    plan_windows,
    staged_team_ids,
    window_query_args,
)
from posthog.dataclasses import frozen
from posthog.models.event.sql import EVENTS_DATA_TABLE

GIB = 1024**3

_COUNTERS = ("staged", "repaired", "pending", "missing", "duplicate_rows", "left_in_windows")


class GeoipVerifyConfig(dagster.Config):
    staging_run_id: str = pydantic.Field(description="The ID of the geoip_backfill_staging_job run to check.")
    team_ids: list[int] | None = pydantic.Field(
        default=None, description="Check only these teams. Leave empty to check every staged team."
    )
    windows: list[IngestionWindowConfig] = pydantic.Field(
        default_factory=list,
        description="The windows the staging run read. Leave empty to skip the count of events left in them.",
    )
    max_event_age_days: int = pydantic.Field(
        default=7, ge=0, description="The max_event_age_days the staging run used."
    )
    team_chunk_size: int = pydantic.Field(default=50, ge=1, description="Teams per read.")
    max_execution_time_seconds: int = pydantic.Field(default=10 * 60, description="ClickHouse max_execution_time.")
    max_memory_usage_bytes: int = pydantic.Field(default=16 * GIB, description="ClickHouse max_memory_usage.")


@frozen
class VerifyPlan:
    table: GeoipStagingTable
    team_ids: tuple[int, ...]
    windows: tuple[IngestionWindow, ...]
    config: GeoipVerifyConfig


def staged_events_query(table: GeoipStagingTable) -> str:
    return f"""
        SELECT
            team_id,
            count(),
            countIf(JSONHas(latest_properties, '$geoip_country_code')),
            sum(copies - 1)
        FROM (
            SELECT team_id, uuid, count() AS copies, argMax(properties, _timestamp) AS latest_properties
            FROM {EVENTS_DATA_TABLE()}
            WHERE team_id IN %(team_ids)s
                AND timestamp >= %(timestamp_from)s AND timestamp <= %(timestamp_to)s
                AND uuid IN (SELECT uuid FROM {table.qualified_name} WHERE team_id IN %(team_ids)s)
            GROUP BY team_id, uuid
        )
        GROUP BY team_id
    """


def left_in_window_query() -> str:
    # A resent row has the staging time as `_timestamp`, outside the window, so the inner query finds the
    # originals and the outer query reads every row of those events.
    return f"""
        SELECT team_id, count()
        FROM (
            SELECT team_id, uuid, argMax(properties, _timestamp) AS latest_properties
            FROM {EVENTS_DATA_TABLE()}
            WHERE team_id IN %(team_ids)s
                AND timestamp >= %(event_time_floor)s AND timestamp < %(event_time_ceiling)s
                AND uuid IN (
                    SELECT uuid FROM {EVENTS_DATA_TABLE()}
                    WHERE {AFFECTED_EVENT_FILTER} AND team_id IN %(team_ids)s
                )
            GROUP BY team_id, uuid
        )
        WHERE NOT JSONHas(latest_properties, '$geoip_country_code')
        GROUP BY team_id
    """


def _chunks(items: Sequence[int], size: int) -> Iterator[tuple[int, ...]]:
    for start in range(0, len(items), size):
        yield tuple(items[start : start + size])


@dagster.op(tags=OWNER_TAG)
def plan_geoip_verify(cluster: dagster.ResourceParam[ClickhouseCluster], config: GeoipVerifyConfig) -> VerifyPlan:
    table = GeoipStagingTable(id=uuid.UUID(config.staging_run_id))
    team_ids = staged_team_ids(cluster, table, config.team_ids)
    windows = plan_windows(config.windows, datetime.now(UTC)) if config.windows else ()
    return VerifyPlan(table=table, team_ids=team_ids, windows=windows, config=config)


@frozen
class StagedTeamSpan:
    team_id: int
    rows: int
    timestamp_from: datetime
    timestamp_to: datetime


@frozen
class Verification:
    cluster: ClickhouseCluster
    plan: VerifyPlan
    query_tags: DagsterTags

    def run(self) -> dict[str, Counter[int]]:
        counts: dict[str, Counter[int]] = {name: Counter() for name in _COUNTERS}
        for team_ids in _chunks(self.plan.team_ids, self.plan.config.team_chunk_size):
            self._count_staged(team_ids, counts)
            for window in self.plan.windows:
                args = {**window_query_args(window, self.plan.config.max_event_age_days), "team_ids": team_ids}
                for team_id, events in self._on_every_shard(left_in_window_query(), args):
                    counts["left_in_windows"][team_id] += events
        for team_id, staged in counts["staged"].items():
            found = counts["repaired"][team_id] + counts["pending"][team_id]
            counts["missing"][team_id] = staged - found
        return counts

    def _count_staged(self, team_ids: tuple[int, ...], counts: dict[str, Counter[int]]) -> None:
        table = self.plan.table.qualified_name

        def staged_per_team(client: Client) -> list[StagedTeamSpan]:
            return [
                StagedTeamSpan(team_id=team_id, rows=rows, timestamp_from=timestamp_from, timestamp_to=timestamp_to)
                for team_id, rows, timestamp_from, timestamp_to in client.execute(
                    f"SELECT team_id, count(), min(timestamp), max(timestamp) FROM {table} FINAL "
                    "WHERE team_id IN %(team_ids)s GROUP BY team_id",
                    {"team_ids": team_ids},
                )
            ]

        staged = [
            span
            for spans in self.cluster.map_one_host_per_shard(tagged(self.query_tags, staged_per_team, product=PRODUCT))
            .result()
            .values()
            for span in spans
        ]
        if not staged:
            return
        for span in staged:
            counts["staged"][span.team_id] += span.rows
        args = {
            "team_ids": team_ids,
            "timestamp_from": f"{min(span.timestamp_from for span in staged):%Y-%m-%d %H:%M:%S.%f}",
            "timestamp_to": f"{max(span.timestamp_to for span in staged):%Y-%m-%d %H:%M:%S.%f}",
        }
        for team_id, events, repaired, duplicate_rows in self._on_every_shard(
            staged_events_query(self.plan.table), args
        ):
            counts["repaired"][team_id] += repaired
            counts["pending"][team_id] += events - repaired
            counts["duplicate_rows"][team_id] += duplicate_rows

    def _on_every_shard(self, query: str, args: dict[str, Any]) -> list[tuple[Any, ...]]:
        workload, node_role = shard_workload()
        settings = {
            "max_execution_time": self.plan.config.max_execution_time_seconds,
            "max_memory_usage": self.plan.config.max_memory_usage_bytes,
        }

        def read(client: Client) -> list[tuple[Any, ...]]:
            return sync_execute(query, args, settings=settings, workload=workload, sync_client=client, flush=False)

        per_shard: dict[int, Callable[[Client], list[tuple[Any, ...]]]] = {
            shard_num: tagged(self.query_tags, read, product=PRODUCT) for shard_num in self.cluster.shards
        }
        result = self.cluster.map_any_host_in_shards_by_role(per_shard, workload=workload, node_role=node_role).result()
        return [row for rows in result.values() for row in rows]


@dagster.op(tags=OWNER_TAG)
def verify_geoip_backfill(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    plan: VerifyPlan,
) -> dict[str, int]:
    counts = Verification(cluster=cluster, plan=plan, query_tags=dagster_tags(context)).run()
    totals = {name: sum(counts[name].values()) for name in _COUNTERS}
    metadata: dict[str, Any] = {
        "teams": dagster.MetadataValue.int(len(plan.team_ids)),
        **{name: dagster.MetadataValue.int(total) for name, total in totals.items()},
    }
    for name in ("pending", "missing", "duplicate_rows", "left_in_windows"):
        top = Counter({team_id: n for team_id, n in counts[name].items() if n})
        metadata[f"{name}_per_team"] = dagster.MetadataValue.json(
            {str(team_id): n for team_id, n in top.most_common(100)}
        )
    context.add_output_metadata(metadata)
    context.log.info(", ".join(f"{name} {total}" for name, total in totals.items()))
    return totals


@dagster.job(tags=OWNER_TAG)
def geoip_backfill_verify_job() -> None:
    """Count the staged events that are repaired, pending, missing and duplicated, per team. Reads only."""
    verify_geoip_backfill(plan_geoip_verify())
