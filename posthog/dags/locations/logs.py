from django.conf import settings

import dagster

from posthog.dags import backups
from posthog.dags.common.resources import BackupsClickhouseClusterResource

from . import resources

_logs_cluster: dagster.ResourceDefinition = BackupsClickhouseClusterResource(
    host=settings.CLICKHOUSE_LOGS_HOST, cluster=settings.CLICKHOUSE_LOGS_CLUSTER
)

defs = dagster.Definitions(
    jobs=[
        backups.non_sharded_backup.with_top_level_resources({"cluster": _logs_cluster}),
    ],
    schedules=[
        backups.full_logs_backup_schedule,
        backups.incremental_logs_backup_schedule,
    ],
    resources=resources,
)
