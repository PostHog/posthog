# NOTE: These are the queues used for logically separating workloads.
# Many queues are consumed by one "consumer" - a worker configured to consume from that queue.
# The goal should be to split up queues based on the type of work being done, so that we can scale effectively
# and change the consumer configs without the need for code changes
#
# Worker consumers config here https://github.com/PostHog/charts/blob/main/config/posthog/prod-us.yaml.gotmpl#L538
# e.g.
#   consumers:
#     - name: priority
#       queues:
#         - email
#         - stats
#     - name: default
#       concurrency: 4
#       queues:
#         - celery # default queue for Celery
#     - name: async
#       concurrency: 4
#       queues:
#         - analytics_queries
#         - subscriptions


import time
import threading

# NOTE: Keep in sync with bin/celery-queues.env
from enum import Enum
from typing import Any

from celery import Task
from prometheus_client import CollectorRegistry, Gauge

from posthog.metrics import pushed_metrics_registry


class PushGatewayTask(Task):
    """
    Base task class that automatically pushes metrics to PushGateway.

    Provides standard duration and success metrics automatically.
    Tasks can add custom metrics via self.metrics_registry.

    Usage:
        @shared_task(bind=True, base=PushGatewayTask, ...)
        def my_task(self):
            # Add custom metrics
            my_gauge = Gauge("my_metric", "Description", registry=self.metrics_registry)
            my_gauge.set(value)

    Note: Tasks using this base class must use `bind=True` and accept `self` as
    the first parameter (typed as `PushGatewayTask`) to access `self.metrics_registry`.
    """

    abstract = True
    _local = threading.local()

    @property
    def metrics_registry(self) -> CollectorRegistry | None:
        return getattr(self._local, "registry", None)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        task_name = self.name.split(".")[-1]

        with pushed_metrics_registry(f"celery_{task_name}") as registry:
            self._local.registry = registry

            duration_gauge = Gauge(
                f"posthog_celery_{task_name}_duration_seconds",
                f"Duration of {task_name}",
                registry=registry,
            )
            success_gauge = Gauge(
                f"posthog_celery_{task_name}_success",
                f"Whether {task_name} succeeded (1) or failed (0)",
                registry=registry,
            )

            start_time = time.monotonic()
            try:
                result = self.run(*args, **kwargs)
                success_gauge.set(1)
                return result
            except Exception:
                success_gauge.set(0)
                raise
            finally:
                duration_gauge.set(time.monotonic() - start_time)
                self._local.registry = None


class CeleryQueue(Enum):
    DEFAULT = "celery"
    STATS = "stats"
    EMAIL = "email"
    LONG_RUNNING = "long_running"  # any task that has a good chance of taking more than a few seconds should go here
    ANALYTICS_QUERIES = "analytics_queries"
    ANALYTICS_LIMITED = "analytics_limited"
    ALERTS = "alerts"
    EXPORTS = "exports"
    SUBSCRIPTION_DELIVERY = "subscription_delivery"
    USAGE_REPORTS = "usage_reports"
    SESSION_REPLAY_EMBEDDINGS = "session_replay_embeddings"
    SESSION_REPLAY_PERSISTENCE = "session_replay_persistence"
    SESSION_REPLAY_GENERAL = "session_replay_general"
    INTEGRATIONS = "integrations"
    FEATURE_FLAGS = "feature-flags"
    FEATURE_FLAGS_LONG_RUNNING = "feature-flags-long-running"
