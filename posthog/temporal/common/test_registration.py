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
    ],
)
def test_validation_rejects(registration: object, message: str) -> None:
    with pytest.raises(TemporalRegistrationError, match=message):
        validate_registration("fixture_product", registration)


@pytest.mark.parametrize(
    "first, second, message",
    [
        (
            TemporalRegistration(queues=(_binding(),)),
            TemporalRegistration(queues=(_binding(workflows=(OtherProductWorkflow,), activities=()),)),
            "both declare a workflow named 'registration-fixture-workflow'",
        ),
        (
            TemporalRegistration(histograms=(HistogramSpec(metric_name="fixture_latency", buckets=(1.0,)),)),
            TemporalRegistration(histograms=(HistogramSpec(metric_name="fixture_latency", buckets=(5.0,)),)),
            "both declare buckets for the metric 'fixture_latency'",
        ),
    ],
    ids=["one workflow name on one queue", "one histogram metric"],
)
def test_loading_rejects_two_products_that_declare_the_same_name(
    first: TemporalRegistration, second: TemporalRegistration, message: str
) -> None:
    modules = [
        SimpleNamespace(__name__="products.fixture_product.backend.facade.temporal", TEMPORAL=first),
        SimpleNamespace(__name__="products.other_product.backend.facade.temporal", TEMPORAL=second),
        # A product that still hands out lists has no declaration, and loading skips it.
        SimpleNamespace(__name__="products.legacy_product.backend.facade.temporal"),
    ]
    with (
        patch("posthog.temporal.common.registration.load_product_modules", return_value=modules),
        pytest.raises(TemporalRegistrationError, match=message),
    ):
        load_registrations.__wrapped__()
