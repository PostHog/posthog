import dagster

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.custom_metrics import MetricsClient
from posthog.dags import slack_alerts

from . import resources


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


# Used for definitions that are shared between locations.
# Mainly sensors
defs = dagster.Definitions(
    sensors=[
        slack_alerts.notify_slack_on_failure,
        *[
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
        ],
    ],
    resources=resources,
)
