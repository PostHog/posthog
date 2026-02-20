from django.conf import settings

import dagster

from posthog.dags import backups
from posthog.dags.common.resources import ClickhouseClusterResource

from . import resources

defs = dagster.Definitions(
    jobs=[
        backups.non_sharded_backup,
    ],
    schedules=[
        backups.full_logs_backup_schedule,
        backups.incremental_logs_backup_schedule,
    ],
    resources={
        **resources,
        "cluster": ClickhouseClusterResource(host=settings.CLICKHOUSE_LOGS_CLUSTER_HOST),
    },
)
