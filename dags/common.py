from enum import Enum

import dagster
from clickhouse_driver.errors import Error, ErrorCodes

from posthog.clickhouse.cluster import (
    ClickhouseCluster,
    ExponentialBackoff,
    RetryPolicy,
    get_cluster,
)
from posthog.clickhouse.custom_metrics import MetricsClient


class JobOwners(str, Enum):
    TEAM_CLICKHOUSE = "team-clickhouse"
    TEAM_REVENUE_ANALYTICS = "team-revenue-analytics"
    TEAM_WEB_ANALYTICS = "team-web-analytics"
    TEAM_ERROR_TRACKING = "team-error-tracking"


class ClickhouseClusterResource(dagster.ConfigurableResource):
    """
    The ClickHouse cluster used to run the job.
    """

    client_settings: dict[str, str] = {
        "lightweight_deletes_sync": "0",
        "max_execution_time": "0",
        "max_memory_usage": "0",
        "mutations_sync": "0",
        "receive_timeout": f"{15 * 60}",  # some synchronous queries like dictionary checksumming can be very slow to return
    }

    def create_resource(self, context: dagster.InitResourceContext) -> ClickhouseCluster:
        return get_cluster(
            context.log,
            client_settings=self.client_settings,
            retry_policy=RetryPolicy(
                max_attempts=8,
                delay=ExponentialBackoff(20),
                exceptions=lambda e: (
                    isinstance(e, Error)
                    and (
                        (
                            e.code
                            in (  # these are typically transient errors and unrelated to the query being executed
                                ErrorCodes.NETWORK_ERROR,
                                ErrorCodes.TOO_MANY_SIMULTANEOUS_QUERIES,
                                ErrorCodes.NOT_ENOUGH_SPACE,
                                ErrorCodes.SOCKET_TIMEOUT,
                                439,  # CANNOT_SCHEDULE_TASK: "Cannot schedule a task: cannot allocate thread"
                            )
                        )
                        # queries that exceed memory limits can be retried if they were killed due to total server
                        # memory consumption, but we should avoid retrying queries that were killed due to query limits
                        or (e.code == ErrorCodes.MEMORY_LIMIT_EXCEEDED and "Memory limit (total) exceeded" in e.message)
                    )
                ),
            ),
        )


def report_job_status_metric(
    context: dagster.RunStatusSensorContext, cluster: dagster.ResourceParam[ClickhouseCluster]
) -> None:
    MetricsClient(cluster).increment(
        "dagster_run_status",
        labels={
            "job_name": context.dagster_run.job_name,
            "status": context.dagster_run.status.name,
        },
    ).result()


job_status_metrics_sensors = [
    dagster.run_status_sensor(
        name=f"{report_job_status_metric.__name__}_{status.name}",
        run_status=status,
        default_status=dagster.DefaultSensorStatus.RUNNING,
        monitor_all_code_locations=True,
    )(report_job_status_metric)
    for status in [
        dagster.DagsterRunStatus.STARTED,
        dagster.DagsterRunStatus.SUCCESS,
        dagster.DagsterRunStatus.FAILURE,
        dagster.DagsterRunStatus.CANCELED,
    ]
]
