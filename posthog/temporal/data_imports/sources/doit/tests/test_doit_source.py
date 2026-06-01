import pytest

from posthog.temporal.data_imports.sources.doit.doit import DOIT_RETRY, MAX_ERROR_BODY_LENGTH, summarize_response_body
from posthog.temporal.data_imports.sources.doit.source import DoItSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestDoItSource:
    def setup_method(self):
        self.source = DoItSource()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.DOIT

    @pytest.mark.parametrize("pattern", ["Report no longer exists"])
    def test_non_retryable_errors_includes_pattern(self, pattern):
        errors = self.source.get_non_retryable_errors()

        assert pattern in errors


class TestSummarizeResponseBody:
    def test_collapses_whitespace(self):
        assert summarize_response_body("hello\n\n   world\t!") == "hello world !"

    def test_truncates_long_body(self):
        html = "<html>" + ("x" * 5000) + "</html>"

        summary = summarize_response_body(html)

        assert summary.endswith("… (truncated)")
        assert len(summary) <= MAX_ERROR_BODY_LENGTH + len("… (truncated)")

    def test_does_not_truncate_short_body(self):
        assert summarize_response_body("not found") == "not found"


class TestDoItRetry:
    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 524])
    def test_transient_statuses_are_retried(self, status):
        # 524 (Cloudflare origin timeout) is the one missing from the shared default forcelist.
        assert status in DOIT_RETRY.status_forcelist

    def test_does_not_raise_on_status(self):
        # Lets the source inspect the final response and raise a sanitized error instead of
        # urllib3 raising MaxRetryError with the raw body.
        assert DOIT_RETRY.raise_on_status is False
