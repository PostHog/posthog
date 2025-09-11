import dagster

from posthog.clickhouse.cluster import ClickhouseCluster, Query

from dags.common import JobOwners


class ErrorConfig(dagster.Config):
    code: int


@dagster.op
def error_op(
    config: ErrorConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    cluster.map_all_hosts(
        Query(
            "SELECT throwIf(true, %(message)s, toInt32(%(code)s))",
            {"message": "an error occurred", "code": config.code},
            {"allow_custom_error_code_in_throwif": "true"},
        ),
    ).result()


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def error():
    error_op()
