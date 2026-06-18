import pytest
from unittest.mock import patch

from posthog.temporal.data_imports.sources.common.http.metrics import (
    _NullCounter,
    _NullHistogram,
    _reset_cache_for_tests,
    get_http_latency_histogram,
    get_http_requests_counter,
    get_http_response_bytes_histogram,
    status_class,
)


@pytest.fixture(autouse=True)
def _reset_instrument_cache():
    """The instrument cache is process-global; clear it between tests."""
    _reset_cache_for_tests()
    yield
    _reset_cache_for_tests()


@pytest.mark.parametrize(
    "code,expected",
    [
        (None, "error"),
        (199, "other"),
        (200, "2xx"),
        (204, "2xx"),
        (299, "2xx"),
        (300, "3xx"),
        (399, "3xx"),
        (400, "4xx"),
        (404, "4xx"),
        (429, "4xx"),
        (499, "4xx"),
        (500, "5xx"),
        (599, "5xx"),
        (600, "other"),
        (700, "other"),
    ],
)
def test_status_class(code: int | None, expected: str):
    assert status_class(code) == expected


def test_null_counter_is_no_op():
    c = _NullCounter()
    # None of these should raise. (Return type is None — tested by mypy.)
    c.add(1)
    c.add(0, {"host": "x"})
    c.add(99, None)


def test_null_histogram_is_no_op():
    h = _NullHistogram()
    h.record(0)
    h.record(123, {"host": "x"})
    h.record(0, None)


def test_get_counter_outside_workflow_returns_null():
    """Outside a Temporal workflow/activity, `workflow.metric_meter()` raises — we fall back to null."""
    counter = get_http_requests_counter(team_id=1, source_type="stripe")
    # Should be able to call .add without error
    counter.add(1, {"host": "api.stripe.com", "status_class": "2xx"})


def test_get_histograms_outside_workflow_return_null():
    latency = get_http_latency_histogram(team_id=1, source_type="stripe")
    bytes_ = get_http_response_bytes_histogram(team_id=1, source_type="stripe")

    latency.record(123)
    bytes_.record(456)


def test_get_counter_uses_meter_when_available():
    """When `workflow.metric_meter()` returns something, the helper should use it."""
    fake_counter = object()
    fake_meter = type(
        "FakeMeter",
        (),
        {
            "with_additional_attributes": lambda self, attrs: self,
            "create_counter": lambda self, name, desc: fake_counter,
        },
    )()

    with patch(
        "posthog.temporal.data_imports.sources.common.http.metrics._safe_metric_meter",
        return_value=fake_meter,
    ):
        result = get_http_requests_counter(team_id=42, source_type="stripe")

    assert result is fake_counter


def test_get_histogram_uses_meter_when_available():
    fake_histogram = object()
    fake_meter = type(
        "FakeMeter",
        (),
        {
            "with_additional_attributes": lambda self, attrs: self,
            "create_histogram": lambda self, name, desc, unit: fake_histogram,
        },
    )()

    with patch(
        "posthog.temporal.data_imports.sources.common.http.metrics._safe_metric_meter",
        return_value=fake_meter,
    ):
        latency = get_http_latency_histogram(team_id=1, source_type="stripe")
        bytes_ = get_http_response_bytes_histogram(team_id=1, source_type="stripe")

    assert latency is fake_histogram
    assert bytes_ is fake_histogram


def test_meter_attributes_include_team_and_source():
    """The meter must be configured with `team_id` (as str) and `source_type`."""
    captured: list[dict] = []

    class FakeMeter:
        def with_additional_attributes(self, attrs):
            captured.append(attrs)
            return self

        def create_counter(self, name, desc):
            return object()

    with patch(
        "posthog.temporal.data_imports.sources.common.http.metrics._safe_metric_meter",
        return_value=FakeMeter(),
    ):
        get_http_requests_counter(team_id=42, source_type="stripe")

    assert captured == [{"team_id": "42", "source_type": "stripe"}]


def test_get_counter_caches_per_team_and_source():
    """Repeated calls for the same (team_id, source_type) must return the same instrument."""
    creates: list[tuple[str, str]] = []

    class FakeMeter:
        def with_additional_attributes(self, attrs):
            return self

        def create_counter(self, name, desc):
            creates.append((name, desc))
            return object()

    with patch(
        "posthog.temporal.data_imports.sources.common.http.metrics._safe_metric_meter",
        return_value=FakeMeter(),
    ):
        first = get_http_requests_counter(team_id=42, source_type="stripe")
        second = get_http_requests_counter(team_id=42, source_type="stripe")
        third = get_http_requests_counter(team_id=42, source_type="hubspot")

    assert first is second
    assert first is not third
    # Two distinct (team_id, source_type) keys → two creates, not three.
    assert len(creates) == 2


def test_get_histogram_caches_per_team_and_source():
    creates: list[tuple[str, str]] = []

    class FakeMeter:
        def with_additional_attributes(self, attrs):
            return self

        def create_histogram(self, name, desc, unit):
            creates.append((name, desc))
            return object()

    with patch(
        "posthog.temporal.data_imports.sources.common.http.metrics._safe_metric_meter",
        return_value=FakeMeter(),
    ):
        a = get_http_latency_histogram(team_id=1, source_type="stripe")
        b = get_http_latency_histogram(team_id=1, source_type="stripe")
        c = get_http_response_bytes_histogram(team_id=1, source_type="stripe")
        d = get_http_response_bytes_histogram(team_id=1, source_type="stripe")

    assert a is b
    assert c is d
    # Two distinct instruments (latency, bytes) for one (team, source) → two creates.
    assert len(creates) == 2


def test_null_recorders_are_also_cached():
    """When the meter is unavailable, the null recorder is still cached so we don't allocate per request."""
    first = get_http_requests_counter(team_id=1, source_type="stripe")
    second = get_http_requests_counter(team_id=1, source_type="stripe")

    assert first is second
