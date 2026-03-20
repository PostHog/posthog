from django.conf import settings

import dagster

from posthog.dags import backups
from posthog.dags.common.resources import BackupsClickhouseClusterResource

from . import resources

defs = dagster.Definitions(
    jobs=[
        backups.non_sharded_backup.with_top_level_resources(
            {
                "cluster": BackupsClickhouseClusterResource(  # type: ignore[dict-item]  # pyright: ignore[reportArgumentType]
                    host=settings.CLICKHOUSE_LOGS_HOST, cluster=settings.CLICKHOUSE_LOGS_CLUSTER
                )
            }
        ),
    ],
    schedules=[
        backups.full_logs_backup_schedule,
        backups.incremental_logs_backup_schedule,
    ],
    resources=resources,
)
