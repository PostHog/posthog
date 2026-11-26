from types import SimpleNamespace

import pytest
from unittest.mock import patch

from temporalio import activity, workflow
from temporalio.worker import Interceptor

from posthog.temporal.common.interceptor import ALL_TASK_QUEUES
from posthog.temporal.common.registration import (
    HistogramSpec,
    QueueBinding,
    TemporalRegistration,
    TemporalRegistrationError,
    load_registrations,
    validate_registration,
)


@workflow.defn(name="registration-fixture-workflow")
class FixtureWorkflow:
    @workflow.run
    async def run(self) -> None:
        return None


class UndecoratedWorkflow:
    pass


@workflow.defn(name="registration-fixture-workflow")
class OtherProductWorkflow:
    @workflow.run
    async def run(self) -> None:
        return None


OtherProductWorkflow.__module__ = "products.other_product.backend.temporal"


@activity.defn(name="registration_fixture_activity")
async def fixture_activity() -> None:
    return None


async def undecorated_activity() -> None:
    return None


class FixtureInterceptor(Interceptor):
    task_queue = ALL_TASK_QUEUES


class QueuelessInterceptor(Interceptor):
    pass


def _binding(**overrides: object) -> QueueBinding:
    fields: dict[str, object] = {
        "queue_setting": "GENERAL_PURPOSE_TASK_QUEUE",
        "workflows": (FixtureWorkflow,),
        "activities": (fixture_activity,),
    }
    return QueueBinding(**(fields | overrides))  # type: ignore[arg-type]


def test_a_complete_declaration_is_valid() -> None:
    validate_registration(
        "fixture_product",
        TemporalRegistration(
            queues=(_binding(),),
            interceptors=(FixtureInterceptor,),
            histograms=(HistogramSpec(metric_name="fixture_latency", buckets=(1.0, 10.0)),),
        ),
    )


@pytest.mark.parametrize(
    "registration, message",
    [
        (object(), "must be a TemporalRegistration"),
        (TemporalRegistration(queues=(_binding(queue_setting="SITE_URL"),)), "no task queue setting"),
        (TemporalRegistration(queues=(_binding(queue_setting="MISSING_TASK_QUEUE"),)), "no task queue setting"),
        (TemporalRegistration(queues=(_binding(workflows=(UndecoratedWorkflow,)),)), "no @workflow.defn"),
        (TemporalRegistration(queues=(_binding(activities=(undecorated_activity,)),)), "no @activity.defn"),
        (TemporalRegistration(queues=(_binding(workflows=(OtherProductWorkflow,)),)), "which other_product owns"),
        (TemporalRegistration(interceptors=(object,)), "no Interceptor class"),  # type: ignore[arg-type]
        (TemporalRegistration(interceptors=(QueuelessInterceptor,)), "names no task_queue"),
        (
            TemporalRegistration(
                histograms=(HistogramSpec(metric_name="fixture_latency", buckets=(1.0,), queue_setting="SITE_URL"),)
            ),
            "no task queue setting",
        ),
    ],
    ids=[
        "not a registration",
        "not a queue setting",
        "missing queue setting",
        "workflow without defn",
        "activity without defn",
        "another product's workflow",
        "interceptor of the wrong type",
        "interceptor without task queue",
        "histogram on no queue setting",
    ],
)
def test_validation_rejects(registration: object, message: str) -> None:
    with pytest.raises(TemporalRegistrationError, match=message):
        validate_registration("fixture_product", registration)


def _facade_module(product: str, registration: TemporalRegistration | None) -> SimpleNamespace:
    module = SimpleNamespace(__name__=f"products.{product}.backend.facade.temporal")
    if registration is not None:
        module.TEMPORAL = registration
    return module


def _histogram(buckets: tuple[float, ...], queue_setting: str | None = None) -> TemporalRegistration:
    return TemporalRegistration(
        histograms=(HistogramSpec(metric_name="fixture_latency", buckets=buckets, queue_setting=queue_setting),)
    )


@pytest.mark.parametrize(
    "first, second, message",
    [
        (
            TemporalRegistration(queues=(_binding(),)),
            TemporalRegistration(queues=(_binding(workflows=(OtherProductWorkflow,), activities=()),)),
            "both declare a workflow named 'registration-fixture-workflow'",
        ),
        (_histogram((1.0,)), _histogram((5.0,)), "both declare buckets for the metric 'fixture_latency'"),
        (
            _histogram((1.0,)),
            _histogram((5.0,), queue_setting="MAX_AI_TASK_QUEUE"),
            "both declare buckets for the metric 'fixture_latency'",
        ),
        (
            TemporalRegistration(
                histograms=(
                    HistogramSpec(metric_name="fixture_latency", buckets=(1.0,)),
                    HistogramSpec(metric_name="fixture_latency", buckets=(5.0,), queue_setting="MAX_AI_TASK_QUEUE"),
                )
            ),
            TemporalRegistration(),
            "both declare buckets for the metric 'fixture_latency'",
        ),
        (TemporalRegistration(), None, "other_product: facade.temporal must declare TEMPORAL"),
    ],
    ids=[
        "one workflow name on one queue",
        "one histogram metric",
        "one histogram metric on every queue",
        "one metric twice in one product",
        "no declaration",
    ],
)
def test_loading_rejects(first: TemporalRegistration, second: TemporalRegistration | None, message: str) -> None:
    modules = [_facade_module("fixture_product", first), _facade_module("other_product", second)]
    with (
        patch("posthog.temporal.common.registration.load_product_modules", return_value=modules),
        pytest.raises(TemporalRegistrationError, match=message),
    ):
        load_registrations.__wrapped__()


def test_loading_accepts_one_histogram_metric_on_two_queues() -> None:
    modules = [
        _facade_module("fixture_product", _histogram((1.0,), queue_setting="MAX_AI_TASK_QUEUE")),
        _facade_module("other_product", _histogram((5.0,), queue_setting="TASKS_TASK_QUEUE")),
    ]
    with patch("posthog.temporal.common.registration.load_product_modules", return_value=modules):
        assert set(load_registrations.__wrapped__()) == {"fixture_product", "other_product"}
