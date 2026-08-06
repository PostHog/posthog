import time
import threading
from typing import Any

from celery import Task
from prometheus_client import CollectorRegistry, Gauge

# Re-exported for the many existing `from posthog.tasks.utils import CeleryQueue` consumers.
# The enum lives in posthog.celery_queues so import-light modules can use it at decorator-eval
# time without triggering the posthog.tasks package init (which imports every task module).
from posthog.celery_queues import CeleryQueue as CeleryQueue
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
