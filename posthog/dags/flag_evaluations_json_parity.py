from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from functools import partial

from django.conf import settings

import dagster
import pydantic
from clickhouse_driver import Client
from clickhouse_driver.errors import ServerException

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole
from posthog.clickhouse.query_tagging import Feature
from posthog.dags.common import JobOwners, dagster_tags
from posthog.dags.flag_evaluations_backfill import GIB, shard_workload, tagged
from posthog.dataclasses import frozen
from posthog.models.flag_evaluations.sql import (
    FLAG_EVALUATIONS_DATA_TABLE,
    FLAG_EVALUATIONS_JSON_DATA_TABLE,
    FLAG_EVALUATIONS_RETENTION_DAYS,
)

_CLUSTER_DOESNT_EXIST = 701

# Hosted development and end-to-end deployments have no flags cluster and hold the table on data nodes.
_PRODUCTION_DEPLOYMENTS = {"US", "EU"}

OWNER_TAG = {"owner": JobOwners.TEAM_FEATURE_FLAGS.value}

_DEFAULT_START_DAYS_AGO = FLAG_EVALUATIONS_RETENTION_DAYS


class FlagEvaluationsJsonParityConfig(dagster.Config):
    start_date: str | None = pydantic.Field(
        default=None,
        description=f"First day to compare (YYYY-MM-DD, UTC, inclusive). Defaults to {_DEFAULT_START_DAYS_AGO} days ago.",
    )
    end_date: str | None = pydantic.Field(
        default=None,
        description=(
            "Day after the last day to compare (YYYY-MM-DD, UTC, exclusive). Defaults to today, so the "
            "comparison covers only completed days."
        ),
    )
    max_listed_mismatches: int = pydantic.Field(
        default=50, description="How many mismatched days, flag keys and duplicate days the failure message lists."
    )
    ingestion_margin_minutes: int = pydantic.Field(
        default=60,
        description=(
            "Skip a call whose newest copy has a Kafka _timestamp less than this many minutes before the job started. Each table "
            "has its own Kafka consumer, so a recent row can be in one table and not yet in the other. A redelivery "
            "that reached only one table can still fail the run for a call that is otherwise settled: run it again "
            "once the margin has passed."
        ),
    )
    max_execution_time_seconds: int = pydantic.Field(
        default=60 * 60, description="ClickHouse max_execution_time for each comparison query, which covers one day."
    )
    max_memory_usage_bytes: int = pydantic.Field(
        default=32 * GIB, description="ClickHouse max_memory_usage for each comparison query, which covers one day."
    )


# The cutoff applies to each call's newest copy. A merged table keeps only that copy and an unmerged one still
# holds the older ones, so a filter on every row would count a call in one table and not in the other.
def _day_query(table: str) -> str:
    return f"""
SELECT day, count()
FROM (
    SELECT toDate(timestamp) AS day, team_id, uuid
    FROM {table}
    WHERE timestamp >= %(start)s AND timestamp < %(end)s
    GROUP BY day, team_id, uuid
    HAVING max(_timestamp) < %(ingested_before)s
)
GROUP BY day
"""


def _flag_query(table: str) -> str:
    return f"""
SELECT day, flag_key, latest_response AS response, count()
FROM (
    SELECT toDate(timestamp) AS day, team_id, flag_key, uuid, argMax(response, _timestamp) AS latest_response
    FROM {table}
    WHERE timestamp >= %(start)s AND timestamp < %(end)s
    GROUP BY day, team_id, flag_key, uuid
    HAVING max(_timestamp) < %(ingested_before)s
)
GROUP BY day, flag_key, response
"""


# FINAL collapses the rows that a merge would collapse, so unmerged copies of one row do not count. A row that
# stays after FINAL has a different sort key from its twin, so no merge will ever remove it.
def _duplicate_query(table: str) -> str:
    return f"""
SELECT toDate(timestamp) AS day, count() - uniqExact(team_id, uuid)
FROM {table} FINAL
WHERE timestamp >= %(start)s AND timestamp < %(end)s AND _timestamp < %(ingested_before)s
GROUP BY day
HAVING count() > uniqExact(team_id, uuid)
"""


@frozen
class CountDiff:
    key: tuple
    legacy: int
    new: int


def compare_counts(legacy: Mapping[tuple, int], new: Mapping[tuple, int]) -> list[CountDiff]:
    """Return each key whose count differs, keys sorted."""
    return [
        CountDiff(key=key, legacy=legacy.get(key, 0), new=new.get(key, 0))
        for key in sorted({*legacy, *new})
        if legacy.get(key, 0) != new.get(key, 0)
    ]


def _read_counts(query: str, params: dict[str, str], settings: dict[str, int], client: Client) -> dict[tuple, int]:
    return {tuple(row[:-1]): row[-1] for row in sync_execute(query, params, settings=settings, sync_client=client)}


@frozen
class FlagsCluster:
    cluster: ClickhouseCluster
    workload: Workload
    node_role: NodeRole


def flags_cluster(cluster: ClickhouseCluster) -> FlagsCluster:
    """The handle for the flags cluster, where sharded_flag_evaluations_json lives, with its workload and role.

    The cluster resource addresses the posthog cluster. A development stack has no flags cluster and holds the
    table on its one host.
    """
    try:
        flags = FlagsCluster(
            cluster=cluster.sibling(settings.CLICKHOUSE_FLAGS_CLUSTER, NodeRole.FLAGS),
            workload=Workload.DEFAULT,
            node_role=NodeRole.FLAGS,
        )
    except ServerException as exc:
        if exc.code != _CLUSTER_DOESNT_EXIST or settings.CLOUD_DEPLOYMENT in _PRODUCTION_DEPLOYMENTS:
            raise
        workload, node_role = shard_workload()
        flags = FlagsCluster(cluster=cluster, workload=workload, node_role=node_role)
    if len(flags.cluster.shards) != 1:
        raise dagster.Failure(
            description=f"The parity check reads one shard, and this cluster has shards {sorted(flags.cluster.shards)}."
        )
    return flags


@dagster.op(tags=OWNER_TAG)
def compare_flag_evaluations_json_parity(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: FlagEvaluationsJsonParityConfig,
) -> None:
    """Compare the distinct uuids of each day, and of each day, flag_key and response, in both tables.

    The count is `uniqExact(team_id, uuid)`, never `count()`, because unmerged ReplacingMergeTree copies make the row
    counts differ. That also hides a call stored twice under different sort keys, so a separate query lists the
    days on which the new table holds a call more than once after a merge would have run. Fails on a differing
    count or a duplicate. The comparison reads only the two tables, so it holds for a new table filled by any
    means.
    """
    today = datetime.now(UTC).date()
    start = (
        date.fromisoformat(config.start_date) if config.start_date else today - timedelta(days=_DEFAULT_START_DAYS_AGO)
    )
    end = date.fromisoformat(config.end_date) if config.end_date else today
    if start >= end:
        raise dagster.Failure(description=f"start_date {start} must be before end_date {end}.")
    flags = flags_cluster(cluster)
    host = flags.cluster.any_host_in_shard_by_roles(min(flags.cluster.shards), [flags.node_role], flags.workload)
    query_tags = dagster_tags(context)
    ingested_before = f"{datetime.now(UTC) - timedelta(minutes=config.ingestion_margin_minutes):%Y-%m-%d %H:%M:%S}"
    query_settings = {
        "max_execution_time": config.max_execution_time_seconds,
        "max_memory_usage": config.max_memory_usage_bytes,
    }

    def counts(query: str, params: dict[str, str]) -> dict[tuple, int]:
        read = partial(_read_counts, query, params, query_settings)
        return flags.cluster.on_host(host, tagged(query_tags, read, feature=Feature.DATA_QUALITY_CHECK)).result()

    legacy, new = FLAG_EVALUATIONS_DATA_TABLE, FLAG_EVALUATIONS_JSON_DATA_TABLE
    day_diffs: list[CountDiff] = []
    flag_diffs: list[CountDiff] = []
    duplicates: list[tuple[tuple, int]] = []
    # ClickHouse keeps every day's uuid set until a query ends, so each query reads one day.
    for offset in range((end - start).days):
        day = start + timedelta(days=offset)
        params = {
            "start": f"{day:%Y-%m-%d} 00:00:00",
            "end": f"{day + timedelta(days=1):%Y-%m-%d} 00:00:00",
            "ingested_before": ingested_before,
        }
        day_diffs += compare_counts(counts(_day_query(legacy), params), counts(_day_query(new), params))
        flag_diffs += compare_counts(counts(_flag_query(legacy), params), counts(_flag_query(new), params))
        duplicates += sorted(counts(_duplicate_query(new), params).items())
        context.log.info(f"Compared {day}")
    context.add_output_metadata(
        {
            "start": dagster.MetadataValue.text(str(start)),
            "end": dagster.MetadataValue.text(str(end)),
            "mismatched_days": dagster.MetadataValue.int(len(day_diffs)),
            "mismatched_flag_keys": dagster.MetadataValue.int(len(flag_diffs)),
            "days_with_duplicates": dagster.MetadataValue.int(len(duplicates)),
        }
    )
    problems: list[str] = []
    if day_diffs or flag_diffs:
        listed = [f"{d.key[0]}: {d.legacy} in {legacy}, {d.new} in {new}" for d in day_diffs] + [
            f"{d.key[0]} {d.key[1]} {d.key[2]}: {d.legacy} in {legacy}, {d.new} in {new}" for d in flag_diffs
        ]
        problems.append(
            f"{len(day_diffs)} day(s) and {len(flag_diffs)} (day, flag_key, response) group(s) differ. "
            f"First {config.max_listed_mismatches}: {'; '.join(listed[: config.max_listed_mismatches])}"
        )
    if duplicates:
        listed = [f"{key[0]}: {extra} extra row(s)" for key, extra in duplicates]
        problems.append(
            f"{len(duplicates)} day(s) hold a call more than once in {new}, which the distinct counts hide. "
            f"First {config.max_listed_mismatches}: {'; '.join(listed[: config.max_listed_mismatches])}"
        )
    if problems:
        raise dagster.Failure(description=" ".join(problems))


@dagster.job(tags=OWNER_TAG)
def flag_evaluations_json_parity_job() -> None:
    """Compare flag_evaluations_json with flag_evaluations over completed days. Fails when any count differs
    or the new table holds a call twice."""
    compare_flag_evaluations_json_parity()
