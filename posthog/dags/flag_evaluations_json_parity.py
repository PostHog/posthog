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
from posthog.cloud_utils import is_cloud
from posthog.dags.common import JobOwners, dagster_tags
from posthog.dags.flag_evaluations_backfill import shard_workload, tagged
from posthog.dataclasses import frozen
from posthog.models.flag_evaluations.sql import (
    FLAG_EVALUATIONS_DATA_TABLE,
    FLAG_EVALUATIONS_JSON_DATA_TABLE,
    FLAG_EVALUATIONS_RETENTION_DAYS,
)

_CLUSTER_DOESNT_EXIST = 701

OWNER_TAG = {"owner": JobOwners.TEAM_FEATURE_FLAGS.value}

_DEFAULT_START_DAYS_AGO = FLAG_EVALUATIONS_RETENTION_DAYS - 1


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


def _day_query(table: str) -> str:
    return f"""
SELECT toDate(timestamp) AS day, uniqExact(uuid)
FROM {table}
WHERE timestamp >= %(start)s AND timestamp < %(end)s
GROUP BY day
"""


def _flag_query(table: str) -> str:
    return f"""
SELECT toDate(timestamp) AS day, flag_key, response, uniqExact(uuid)
FROM {table}
WHERE timestamp >= %(start)s AND timestamp < %(end)s
GROUP BY day, flag_key, response
"""


# FINAL collapses the rows that a merge would collapse, so unmerged copies of one row do not count. A row that
# stays after FINAL has a different sort key from its twin, so no merge will ever remove it.
def _duplicate_query(table: str) -> str:
    return f"""
SELECT toDate(timestamp) AS day, count() - uniqExact(uuid)
FROM {table} FINAL
WHERE timestamp >= %(start)s AND timestamp < %(end)s
GROUP BY day
HAVING count() > uniqExact(uuid)
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


def _read_counts(query: str, params: dict[str, str], client: Client) -> dict[tuple, int]:
    return {tuple(row[:-1]): row[-1] for row in sync_execute(query, params, sync_client=client)}


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
        return FlagsCluster(
            cluster=cluster.sibling(settings.CLICKHOUSE_FLAGS_CLUSTER, NodeRole.FLAGS),
            workload=Workload.DEFAULT,
            node_role=NodeRole.FLAGS,
        )
    except ServerException as exc:
        if exc.code != _CLUSTER_DOESNT_EXIST or is_cloud():
            raise
        workload, node_role = shard_workload()
        return FlagsCluster(cluster=cluster, workload=workload, node_role=node_role)


@dagster.op(tags=OWNER_TAG)
def compare_flag_evaluations_json_parity(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: FlagEvaluationsJsonParityConfig,
) -> None:
    """Compare the distinct uuids of each day, and of each day, flag_key and response, in both tables.

    The count is `uniqExact(uuid)`, never `count()`, because unmerged ReplacingMergeTree copies make the row
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
    params = {"start": f"{start:%Y-%m-%d} 00:00:00", "end": f"{end:%Y-%m-%d} 00:00:00"}

    def counts(query: str) -> dict[tuple, int]:
        return flags.cluster.on_host(host, tagged(query_tags, partial(_read_counts, query, params))).result()

    legacy, new = FLAG_EVALUATIONS_DATA_TABLE, FLAG_EVALUATIONS_JSON_DATA_TABLE
    day_diffs = compare_counts(counts(_day_query(legacy)), counts(_day_query(new)))
    flag_diffs = compare_counts(counts(_flag_query(legacy)), counts(_flag_query(new)))
    duplicates = sorted(counts(_duplicate_query(new)).items())
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
