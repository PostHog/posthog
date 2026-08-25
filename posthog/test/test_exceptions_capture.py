from unittest import mock

from posthog.exceptions_capture import (
    ambient_exception_properties,
    bind_exception_context,
    capture_exception,
    exception_context,
)

_MODULE = "posthog.exceptions_capture"


def test_exception_context_scopes_and_restores_properties():
    baseline = dict(ambient_exception_properties())
    with exception_context(source="a"):
        assert ambient_exception_properties()["source"] == "a"
        with exception_context(schema="b"):
            # Nested contexts accumulate.
            assert ambient_exception_properties() == {**baseline, "source": "a", "schema": "b"}
        assert "schema" not in ambient_exception_properties()
    assert ambient_exception_properties() == baseline


def test_capture_exception_merges_ambient_and_explicit_properties():
    # Ambient context flows into captured exceptions; explicit call-site properties win on collision.
    with (
        mock.patch("posthog.clickhouse.query_tagging.get_query_tags") as mock_tags,
        mock.patch("posthoganalytics.api_key", "phc_test"),
        mock.patch("posthoganalytics.capture_exception", return_value=None) as mock_capture,
    ):
        mock_tags.return_value.model_dump.return_value = {}
        error = ValueError("boom")
        with exception_context(warehouse_sources_source_type="Elasticsearch", warehouse_sources_job_id="j1"):
            capture_exception(error, additional_properties={"warehouse_sources_job_id": "override", "extra": 1})

    props = mock_capture.call_args.kwargs["properties"]
    assert props["warehouse_sources_source_type"] == "Elasticsearch"
    assert props["warehouse_sources_job_id"] == "override"
    assert props["extra"] == 1


def test_bind_exception_context_is_fire_and_forget_within_scope():
    with exception_context():
        bind_exception_context(k="v")
        assert ambient_exception_properties()["k"] == "v"
    assert "k" not in ambient_exception_properties()
