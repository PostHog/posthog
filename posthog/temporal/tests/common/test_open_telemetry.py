import warnings

from opentelemetry.sdk.resources import Resource
from temporalio.contrib.opentelemetry import ReplaySafeTracerProvider

from posthog.temporal.common.open_telemetry import CachingReplaySafeTracerProvider


def test_repeated_get_tracer_does_not_reset_warning_registries() -> None:
    provider = CachingReplaySafeTracerProvider.create(Resource.create(attributes={"service.name": "test"}))
    assert isinstance(provider, ReplaySafeTracerProvider)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("default")
        first_tracer = provider.get_tracer("temporalio.contrib.opentelemetry")

        for _ in range(3):
            assert provider.get_tracer("temporalio.contrib.opentelemetry") is first_tracer
            warnings.warn("probe warning", UserWarning, stacklevel=1)

    assert [str(warning.message) for warning in caught] == ["probe warning"]
