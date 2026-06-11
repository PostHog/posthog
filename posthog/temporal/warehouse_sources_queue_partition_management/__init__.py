from posthog.temporal.warehouse_sources_queue_partition_management.activities import (
    manage_warehouse_sources_queue_partitions,
)
from posthog.temporal.warehouse_sources_queue_partition_management.workflows import (
    WarehouseSourcesQueuePartitionManagementWorkflow,
)

WORKFLOWS = [WarehouseSourcesQueuePartitionManagementWorkflow]
ACTIVITIES = [manage_warehouse_sources_queue_partitions]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
]
