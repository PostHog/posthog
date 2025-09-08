from dataclasses import dataclass

from django.conf import settings


@dataclass
class TemporalTaskQueuesDC:
    GENERAL_PURPOSE_TASK_QUEUE: str
    DATA_WAREHOUSE_TASK_QUEUE: str
    MAX_AI_TASK_QUEUE: str
    DATA_WAREHOUSE_COMPACTION_TASK_QUEUE: str
    BATCH_EXPORTS_TASK_QUEUE: str
    DATA_MODELING_TASK_QUEUE: str
    SYNC_BATCH_EXPORTS_TASK_QUEUE: str
    TASKS_TASK_QUEUE: str
    TEST_TASK_QUEUE: str
    BILLING_TASK_QUEUE: str
    VIDEO_EXPORT_TASK_QUEUE: str


_TemporalTaskQueues = TemporalTaskQueuesDC(
    GENERAL_PURPOSE_TASK_QUEUE="general-purpose-task-queue",
    DATA_WAREHOUSE_TASK_QUEUE="data-warehouse-task-queue",
    MAX_AI_TASK_QUEUE="max-ai-task-queue",
    DATA_WAREHOUSE_COMPACTION_TASK_QUEUE="data-warehouse-compaction-task-queue",
    BATCH_EXPORTS_TASK_QUEUE="batch-exports-task-queue",
    DATA_MODELING_TASK_QUEUE="data-modeling-task-queue",
    SYNC_BATCH_EXPORTS_TASK_QUEUE="no-sandbox-python-django",
    TASKS_TASK_QUEUE="tasks-task-queue",
    TEST_TASK_QUEUE="test-task-queue",
    BILLING_TASK_QUEUE="billing-task-queue",
    VIDEO_EXPORT_TASK_QUEUE="video-export-task-queue",
)


_TemporalTaskQueuesDebug = TemporalTaskQueuesDC(
    GENERAL_PURPOSE_TASK_QUEUE="general-purpose-task-queue",
    DATA_WAREHOUSE_TASK_QUEUE="general-purpose-task-queue",
    MAX_AI_TASK_QUEUE="general-purpose-task-queue",
    DATA_WAREHOUSE_COMPACTION_TASK_QUEUE="general-purpose-task-queue",
    BATCH_EXPORTS_TASK_QUEUE="general-purpose-task-queue",
    DATA_MODELING_TASK_QUEUE="general-purpose-task-queue",
    SYNC_BATCH_EXPORTS_TASK_QUEUE="general-purpose-task-queue",
    TASKS_TASK_QUEUE="general-purpose-task-queue",
    TEST_TASK_QUEUE="general-purpose-task-queue",
    BILLING_TASK_QUEUE="general-purpose-task-queue",
    VIDEO_EXPORT_TASK_QUEUE="general-purpose-task-queue",
)


TemporalTaskQueues = _TemporalTaskQueuesDebug if settings.DEBUG else _TemporalTaskQueues
