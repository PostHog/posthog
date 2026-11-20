"""The declaration a product uses to host its Temporal code on core's worker and scheduler.

A product sets `TEMPORAL = TemporalRegistration(...)` in `backend/facade/temporal.py`. Core finds it
with `load_product_modules`, so core imports no product's Temporal code by name. See the Temporal
section of products/architecture.md.
"""

from collections.abc import Callable, Coroutine, Iterable
from functools import cache
from typing import Any, Protocol

from django.conf import settings

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Interceptor

from posthog.dataclasses import frozen
from posthog.products import load_product_modules

REGISTRATION_MODULE = "facade.temporal"
REGISTRATION_ATTRIBUTE = "TEMPORAL"


class ActivityDefinition(Protocol):
    # An activity is a sync or async function with any signature, so only the call shape and the
    # function name are typed. The validator checks @activity.defn.
    __name__: str

    def __call__(self, *args: Any, **kwargs: Any) -> object: ...


@frozen
class QueueBinding:
    # The name of a `*_TASK_QUEUE` setting in posthog/settings/temporal.py, not its value. Under DEBUG
    # every queue setting resolves to one development queue, so tools such as the workflow catalog
    # need the name.
    queue_setting: str
    workflows: tuple[type, ...] = ()
    activities: tuple[ActivityDefinition, ...] = ()

    @property
    def task_queue(self) -> str:
        return getattr(settings, self.queue_setting)


@frozen
class HistogramSpec:
    metric_name: str
    buckets: tuple[float, ...]
    # The name of the `*_TASK_QUEUE` setting whose worker uses these buckets, or None for every worker.
    queue_setting: str | None = None

    @classmethod
    def for_metrics(
        cls, metric_names: Iterable[str], buckets: Iterable[float], queue_setting: str | None = None
    ) -> tuple["HistogramSpec", ...]:
        bucket_values = tuple(buckets)
        return tuple(cls(metric_name=name, buckets=bucket_values, queue_setting=queue_setting) for name in metric_names)

    def applies_to(self, task_queue: str) -> bool:
        return self.queue_setting is None or getattr(settings, self.queue_setting) == task_queue


# The scheduler calls a reconciler with a connected client. It creates, updates or deletes the
# product's schedules.
ScheduleReconciler = Callable[[Client], Coroutine[Any, Any, None]]

# Maps a workflow type and a workflow id to a log source and a log source id, or to None for a
# workflow that is not the product's. The log pipeline skips a resolver that raises and reports the error.
LogSourceResolver = Callable[[str, str], tuple[str, str] | None]


@frozen
class TemporalRegistration:
    queues: tuple[QueueBinding, ...] = ()
    # Like core's own interceptors, each one applies to every task queue it supports.
    interceptors: tuple[type[Interceptor], ...] = ()
    # Core's own buckets win for a metric that core configures.
    histograms: tuple[HistogramSpec, ...] = ()
    schedules: tuple[ScheduleReconciler, ...] = ()
    log_sources: tuple[LogSourceResolver, ...] = ()


class TemporalRegistrationError(Exception):
    pass


def _owner(member: object) -> str | None:
    # Product code lives in `products.<product>....`; core code has no product owner.
    parts = getattr(member, "__module__", "").split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "products" else None


def _check_member(product: str, member: object, description: str) -> None:
    owner = _owner(member)
    if owner is not None and owner != product:
        raise TemporalRegistrationError(f"{product} declares {description} {member!r}, which {owner} owns")


def _check_queue_setting(product: str, queue_setting: str) -> None:
    value = getattr(settings, queue_setting, None)
    if not queue_setting.endswith("_TASK_QUEUE") or not isinstance(value, str) or not value:
        raise TemporalRegistrationError(f"{product} binds to {queue_setting!r}, which is no task queue setting")


def _check_binding(product: str, binding: object) -> None:
    if not isinstance(binding, QueueBinding):
        raise TemporalRegistrationError(f"{product} declares {binding!r} as a queue, but it is no QueueBinding")
    _check_queue_setting(product, binding.queue_setting)
    for workflow_class in binding.workflows:
        if workflow._Definition.from_class(workflow_class) is None:
            raise TemporalRegistrationError(f"{product} declares {workflow_class!r}, which has no @workflow.defn")
        _check_member(product, workflow_class, "the workflow")
    for activity_function in binding.activities:
        if activity._Definition.from_callable(activity_function) is None:
            raise TemporalRegistrationError(f"{product} declares {activity_function!r}, which has no @activity.defn")
        _check_member(product, activity_function, "the activity")


def _check_interceptor(product: str, interceptor: object) -> None:
    if not (isinstance(interceptor, type) and issubclass(interceptor, Interceptor)):
        raise TemporalRegistrationError(f"{product} declares {interceptor!r}, which is no Interceptor class")
    # The worker runs an interceptor only on the task queues its `task_queue` attribute names.
    if not hasattr(interceptor, "task_queue"):
        raise TemporalRegistrationError(f"{product} declares {interceptor!r}, which names no task_queue")
    _check_member(product, interceptor, "the interceptor")


def validate_registration(product: str, registration: object) -> None:
    """Raise TemporalRegistrationError when a product's declaration is not one core can host."""
    if not isinstance(registration, TemporalRegistration):
        raise TemporalRegistrationError(
            f"{product}: {REGISTRATION_MODULE}.{REGISTRATION_ATTRIBUTE} must be a TemporalRegistration"
        )
    for binding in registration.queues:
        _check_binding(product, binding)
    for interceptor in registration.interceptors:
        _check_interceptor(product, interceptor)
    for histogram in registration.histograms:
        if not isinstance(histogram, HistogramSpec):
            raise TemporalRegistrationError(f"{product} declares {histogram!r}, which is no HistogramSpec")
        if histogram.queue_setting is not None:
            _check_queue_setting(product, histogram.queue_setting)
    for callback in (*registration.schedules, *registration.log_sources):
        if not callable(callback):
            raise TemporalRegistrationError(f"{product} declares {callback!r} as a callback, but it is not callable")
        _check_member(product, callback, "the callback")


def _check_unique_histograms(registrations: dict[str, TemporalRegistration]) -> None:
    # Two declarations may set buckets for one metric only on different queue settings. Under DEBUG and on a
    # single-queue stack every setting resolves to one queue, so there the declaration that loads last wins.
    declared: dict[str, list[tuple[str, str | None]]] = {}
    for product, registration in registrations.items():
        for histogram in registration.histograms:
            claims = declared.setdefault(histogram.metric_name, [])
            for other_product, other_queue in claims:
                if None in (histogram.queue_setting, other_queue) or histogram.queue_setting == other_queue:
                    raise TemporalRegistrationError(
                        f"{product} and {other_product} both declare buckets for the metric {histogram.metric_name!r}"
                    )
            claims.append((product, histogram.queue_setting))


class _NameClaims:
    """Temporal finds a workflow or an activity by name, and under DEBUG every queue is one queue."""

    def __init__(self) -> None:
        self._claims: dict[tuple[str, str, str | None], tuple[str, object]] = {}

    def claim(self, product: str, task_queue: str, kind: str, name: str | None, member: object) -> None:
        other_product, other_member = self._claims.setdefault((task_queue, kind, name), (product, member))
        if other_member is not member:
            raise TemporalRegistrationError(
                f"{product} and {other_product} both declare a {kind} named {name!r} on {task_queue}"
            )


def _check_unique_names(registrations: dict[str, TemporalRegistration]) -> None:
    claims = _NameClaims()
    for product, registration in registrations.items():
        for binding in registration.queues:
            task_queue = binding.task_queue
            for workflow_class in binding.workflows:
                name = workflow._Definition.must_from_class(workflow_class).name
                claims.claim(product, task_queue, "workflow", name, workflow_class)
            for activity_function in binding.activities:
                name = activity._Definition.must_from_callable(activity_function).name
                claims.claim(product, task_queue, "activity", name, activity_function)


@cache
def load_registrations() -> dict[str, TemporalRegistration]:
    """Every product's validated declaration, by product name."""
    registrations: dict[str, TemporalRegistration] = {}
    for module in load_product_modules(REGISTRATION_MODULE):
        # Product apps are named `products.<product>.backend`.
        product = module.__name__.split(".")[1]
        declared = getattr(module, REGISTRATION_ATTRIBUTE, None)
        if declared is None:
            raise TemporalRegistrationError(
                f"{product}: {REGISTRATION_MODULE} must declare {REGISTRATION_ATTRIBUTE}, or the worker hosts none of its code"
            )
        validate_registration(product, declared)
        registrations[product] = declared
    _check_unique_histograms(registrations)
    _check_unique_names(registrations)
    return registrations


@cache
def combined_registration() -> TemporalRegistration:
    """All products' declarations as one, which is what the worker, the scheduler and the catalog read."""
    queues: list[QueueBinding] = []
    interceptors: list[type[Interceptor]] = []
    histograms: list[HistogramSpec] = []
    schedules: list[ScheduleReconciler] = []
    log_sources: list[LogSourceResolver] = []
    for registration in load_registrations().values():
        queues.extend(registration.queues)
        interceptors.extend(registration.interceptors)
        histograms.extend(registration.histograms)
        schedules.extend(registration.schedules)
        log_sources.extend(registration.log_sources)
    return TemporalRegistration(
        queues=tuple(queues),
        interceptors=tuple(interceptors),
        histograms=tuple(histograms),
        schedules=tuple(schedules),
        log_sources=tuple(log_sources),
    )
