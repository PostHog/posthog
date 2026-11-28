from posthog.temporal.common.registration import HistogramSpec, QueueBinding, TemporalRegistration

from products.alerts_platform.backend.temporal.appearance import (
    APPEARANCE_EVALUATION_ACTIVITIES,
    APPEARANCE_EVALUATION_WORKFLOWS,
)
from products.alerts_platform.backend.temporal.metrics import (
    ALERTS_PLATFORM_LATENCY_HISTOGRAM_BUCKETS,
    ALERTS_PLATFORM_LATENCY_HISTOGRAM_METRICS,
    ALERTS_PLATFORM_TICK_HISTOGRAM_BUCKETS,
    ALERTS_PLATFORM_TICK_HISTOGRAM_METRICS,
    ALERTS_PLATFORM_TICK_KEYS_BUCKETS,
    ALERTS_PLATFORM_TICK_KEYS_METRICS,
)
from products.alerts_platform.backend.temporal.registrar import REGISTRAR_ACTIVITIES, REGISTRAR_WORKFLOWS
from products.alerts_platform.backend.temporal.schedule import (
    create_alerts_platform_expired_holds_schedule,
    create_alerts_platform_inventory_schedule,
    create_alerts_platform_registrar_schedule,
    create_alerts_platform_tick_schedule,
)
from products.alerts_platform.backend.temporal.sources import source_evaluation_timeout
from products.alerts_platform.backend.temporal.telemetry import AlertsPlatformTelemetryInterceptor
from products.alerts_platform.backend.temporal.workflows import (
    DELIVERY_ACTIVITIES,
    DELIVERY_EXECUTION_TIMEOUT,
    DELIVERY_WORKFLOWS,
    EVALUATION_ACTIVITIES,
    EVALUATION_WORKFLOWS,
    SHARED_ORCHESTRATION_ACTIVITIES,
    SHARED_ORCHESTRATION_WORKFLOWS,
    record_and_start_deliveries,
    start_deliveries,
)

__all__ = [
    "APPEARANCE_EVALUATION_ACTIVITIES",
    "APPEARANCE_EVALUATION_WORKFLOWS",
    "ALERTS_PLATFORM_LATENCY_HISTOGRAM_BUCKETS",
    "ALERTS_PLATFORM_LATENCY_HISTOGRAM_METRICS",
    "ALERTS_PLATFORM_TICK_HISTOGRAM_BUCKETS",
    "ALERTS_PLATFORM_TICK_HISTOGRAM_METRICS",
    "ALERTS_PLATFORM_TICK_KEYS_BUCKETS",
    "ALERTS_PLATFORM_TICK_KEYS_METRICS",
    "DELIVERY_ACTIVITIES",
    "DELIVERY_EXECUTION_TIMEOUT",
    "DELIVERY_WORKFLOWS",
    "EVALUATION_ACTIVITIES",
    "EVALUATION_WORKFLOWS",
    "REGISTRAR_ACTIVITIES",
    "REGISTRAR_WORKFLOWS",
    "SHARED_ORCHESTRATION_ACTIVITIES",
    "SHARED_ORCHESTRATION_WORKFLOWS",
    "AlertsPlatformTelemetryInterceptor",
    "create_alerts_platform_expired_holds_schedule",
    "create_alerts_platform_inventory_schedule",
    "create_alerts_platform_registrar_schedule",
    "create_alerts_platform_tick_schedule",
    "source_evaluation_timeout",
    "record_and_start_deliveries",
    "start_deliveries",
]

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="ALERTS_PLATFORM_SHARED_ORCHESTRATION_TASK_QUEUE",
            workflows=tuple(SHARED_ORCHESTRATION_WORKFLOWS),
            activities=tuple(SHARED_ORCHESTRATION_ACTIVITIES),
        ),
        QueueBinding(
            queue_setting="ALERTS_PLATFORM_EVALUATION_TASK_QUEUE",
            workflows=(*EVALUATION_WORKFLOWS, *APPEARANCE_EVALUATION_WORKFLOWS),
            activities=(*EVALUATION_ACTIVITIES, *APPEARANCE_EVALUATION_ACTIVITIES),
        ),
        QueueBinding(
            queue_setting="ALERTS_PLATFORM_DELIVERY_TASK_QUEUE",
            workflows=tuple(DELIVERY_WORKFLOWS),
            activities=tuple(DELIVERY_ACTIVITIES),
        ),
        QueueBinding(
            queue_setting="ALERTS_PLATFORM_REGISTRAR_TASK_QUEUE",
            workflows=tuple(REGISTRAR_WORKFLOWS),
            activities=tuple(REGISTRAR_ACTIVITIES),
        ),
    ),
    schedules=(
        create_alerts_platform_tick_schedule,
        create_alerts_platform_inventory_schedule,
        create_alerts_platform_expired_holds_schedule,
        create_alerts_platform_registrar_schedule,
    ),
    interceptors=(AlertsPlatformTelemetryInterceptor,),
    histograms=(
        *HistogramSpec.for_metrics(
            ALERTS_PLATFORM_LATENCY_HISTOGRAM_METRICS, ALERTS_PLATFORM_LATENCY_HISTOGRAM_BUCKETS
        ),
        *HistogramSpec.for_metrics(ALERTS_PLATFORM_TICK_HISTOGRAM_METRICS, ALERTS_PLATFORM_TICK_HISTOGRAM_BUCKETS),
        *HistogramSpec.for_metrics(ALERTS_PLATFORM_TICK_KEYS_METRICS, ALERTS_PLATFORM_TICK_KEYS_BUCKETS),
    ),
)
