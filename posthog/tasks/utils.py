import time
import threading
from typing import Any

from celery import Task
from celery.exceptions import TaskPredicate
from prometheus_client import CollectorRegistry, Gauge

# Re-exported for the many existing `from posthog.tasks.utils import CeleryQueue` consumers.
# The enum lives in posthog.celery_queues so import-light modules can use it at decorator-eval
# time without triggering the posthog.tasks package init (which imports every task module).
from posthog.celery_queues import CeleryQueue as CeleryQueue
from posthog.metrics import push_registry, pushed_metrics_registry

# A run that hits its soft time limit makes the failure push after that limit.
# The push must end before the hard limit kills the worker. Otherwise Celery loses the task's own exception.
FAILURE_PUSH_TIMEOUT_SECONDS = 5


class PushGatewayTask(Task):
    """
    Base task class that automatically pushes metrics to PushGateway.

    Provides standard duration and success metrics automatically.
    Tasks can add custom metrics via self.metrics_registry.

    A run that returns replaces the job's group with the duration, success = 1, and the task's custom metrics.
    A run that raises an Exception pushes only the duration and success = 0. The custom metrics keep the values of the last run that returned.
    A run that raises a Celery TaskPredicate (Retry, Ignore, Reject) pushes nothing, because Celery does not count it as a failure.

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
        job_name = f"celery_{task_name}"
        start_time = time.monotonic()

        try:
            with pushed_metrics_registry(job_name) as registry:
                self._local.registry = registry
                result = self.run(*args, **kwargs)
                self._set_run_metrics(registry, task_name, time.monotonic() - start_time, success=True)
                return result
        except TaskPredicate:
            raise
        except Exception:
            failure_registry = CollectorRegistry()
            self._set_run_metrics(failure_registry, task_name, time.monotonic() - start_time, success=False)
            push_registry(job_name, failure_registry, replace_group=False, timeout=FAILURE_PUSH_TIMEOUT_SECONDS)
            raise
        finally:
            self._local.registry = None

    @staticmethod
    def _set_run_metrics(registry: CollectorRegistry, task_name: str, duration: float, *, success: bool) -> None:
        Gauge(
            f"posthog_celery_{task_name}_duration_seconds",
            f"Duration of {task_name}",
            registry=registry,
        ).set(duration)
        Gauge(
            f"posthog_celery_{task_name}_success",
            f"Whether {task_name} succeeded (1) or failed (0)",
            registry=registry,
        ).set(1 if success else 0)
