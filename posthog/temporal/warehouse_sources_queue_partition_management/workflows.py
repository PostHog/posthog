from datetime import timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.warehouse_sources_queue_partition_management.activities import (
        manage_warehouse_sources_queue_partitions,
    )
    from posthog.temporal.warehouse_sources_queue_partition_management.types import PartitionManagementInput


@temporalio.workflow.defn(name="warehouse-sources-queue-partition-management")
class WarehouseSourcesQueuePartitionManagementWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PartitionManagementInput:
        return PartitionManagementInput.model_validate_json(inputs[0]) if inputs else PartitionManagementInput()

    @temporalio.workflow.run
    async def run(self, inputs: PartitionManagementInput) -> dict:
        return await temporalio.workflow.execute_activity(
            manage_warehouse_sources_queue_partitions,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
