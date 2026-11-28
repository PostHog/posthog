"""
Temporal registration wiring for data_modeling.

Declares the workflow and activity lists the Temporal worker bootstrap loads. Helpers for
tests in other products live in ``facade/testing.py``.

Imports temporalio and the activity modules, so it must only be imported off the
``django.setup()`` path.
"""

from posthog.temporal.common.registration import HistogramSpec, QueueBinding, TemporalRegistration

from products.data_modeling.backend.facade.temporal_metrics import (
    DATA_MODELING_DURATION_HISTOGRAM_BUCKETS,
    DATA_MODELING_DURATION_HISTOGRAM_METRICS,
    DATA_MODELING_LATENCY_HISTOGRAM_BUCKETS,
    DATA_MODELING_LATENCY_HISTOGRAM_METRICS,
)
from products.data_modeling.backend.temporal import registration

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="DATA_WAREHOUSE_TASK_QUEUE",
            workflows=tuple(registration.WORKFLOWS),
            activities=tuple(registration.ACTIVITIES),
        ),
        QueueBinding(
            queue_setting="DATA_WAREHOUSE_METADATA_TASK_QUEUE",
            workflows=tuple(registration.SEMANTIC_ENRICHMENT_WORKFLOWS),
            activities=tuple(registration.SEMANTIC_ENRICHMENT_ACTIVITIES),
        ),
        QueueBinding(
            queue_setting="DATA_MODELING_TASK_QUEUE",
            workflows=tuple(registration.WORKFLOWS),
            activities=tuple(registration.ACTIVITIES),
        ),
    ),
    histograms=(
        *HistogramSpec.for_metrics(
            DATA_MODELING_LATENCY_HISTOGRAM_METRICS,
            DATA_MODELING_LATENCY_HISTOGRAM_BUCKETS,
            queue_setting="DATA_MODELING_TASK_QUEUE",
        ),
        *HistogramSpec.for_metrics(
            DATA_MODELING_DURATION_HISTOGRAM_METRICS,
            DATA_MODELING_DURATION_HISTOGRAM_BUCKETS,
            queue_setting="DATA_MODELING_TASK_QUEUE",
        ),
    ),
)
