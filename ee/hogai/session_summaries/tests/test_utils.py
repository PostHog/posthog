from datetime import datetime, UTC
from pathlib import Path
import tempfile

import pytest

from ee.hogai.session_summaries.constants import SESSION_SUMMARIES_SYNC_MODEL
from ee.hogai.session_summaries.utils import (
    get_column_index,
    prepare_datetime,
    serialize_to_sse_event,
    shorten_url,
    estimate_tokens_from_strings,
    estimate_tokens_from_template_files,
)


def test_get_column_index_success() -> None:
    columns = ["event", "timestamp", "elements_chain"]
    assert get_column_index(columns, "timestamp") == 1
    assert get_column_index(columns, "event") == 0
    assert get_column_index(columns, "elements_chain") == 2


def test_get_column_index_not_found() -> None:
    columns = ["event", "timestamp", "elements_chain"]
    with pytest.raises(
        ValueError, match="Column nonexistent not found in the columns: \\['event', 'timestamp', 'elements_chain'\\]"
    ):
        get_column_index(columns, "nonexistent")


@pytest.mark.parametrize(
    "input_value,expected",
    [
        ("2024-03-20T15:30:45", datetime(2024, 3, 20, 15, 30, 45)),
        ("2024-03-20T15:30:45.123456", datetime(2024, 3, 20, 15, 30, 45, 123456)),
        ("2024-03-20T15:30:45+00:00", datetime(2024, 3, 20, 15, 30, 45, tzinfo=UTC)),
        ("2024-03-20T15:30:45Z", datetime(2024, 3, 20, 15, 30, 45, tzinfo=UTC)),
    ],
)
def test_prepare_datetime_string_inputs(input_value: str, expected: datetime) -> None:
    result = prepare_datetime(input_value)
    assert result == expected
    assert isinstance(result, datetime)


def test_prepare_datetime_datetime_input() -> None:
    input_dt = datetime(2024, 3, 20, 15, 30, 45)
    result = prepare_datetime(input_dt)

    assert result == input_dt
    assert result is input_dt  # Should return the same object


@pytest.mark.parametrize(
    "url,expected",
    [
        # Short URLs should remain unchanged
        ("https://example.com/path", "https://example.com/path"),
        ("https://example.com/path?q=123", "https://example.com/path?q=123"),
        # Long path without query/fragment should remain unchanged
        ("https://example.com/" + "very/long/path/" * 10, "https://example.com/" + "very/long/path/" * 10),
        # Long query should be shortened
        (f"https://example.com/path?q={'a' * 300}", f"https://example.com/path?q={'a' * 111}[...]{'a' * 113}"),
        # # Long fragment should be shortened
        (f"https://example.com/path#{'b' * 300}", f"https://example.com/path#{'b' * 113}[...]{'b' * 113}"),
        # When both query and fragment are present, longer one gets shortened
        (
            f"https://example.com/path?short=1#{'c' * 300}",
            f"https://example.com/path?short=1#{'c' * 109}[...]{'c' * 109}",
        ),
        (
            f"https://example.com/path?q={'d' * 300}#short",
            f"https://example.com/path?q={'d' * 108}[...]{'d' * 110}#short",
        ),
    ],
)
def test_shorten_url(url: str, expected: str) -> None:
    max_length = 256
    shortened_url = shorten_url(url, max_length)
    assert shortened_url == expected
    assert len(shortened_url) <= max_length


@pytest.mark.parametrize(
    "event_label,event_data,expected",
    [
        # Basic case with simple string data
        ("test-event", "hello world", "event: test-event\ndata: hello world\n\n"),
        # JSON object data
        ("json-event", '{"key": "value"}', 'event: json-event\ndata: {"key": "value"}\n\n'),
        # JSON array data
        ("array-event", "[1,2,3]", "event: array-event\ndata: [1,2,3]\n\n"),
        # Event label with newlines
        ("test\nevent", "data", "event: test\\nevent\ndata: data\n\n"),
        # Non-JSON data with newlines
        ("test-event", "hello\nworld", "event: test-event\ndata: hello\\nworld\n\n"),
        # Empty data
        ("empty-event", "", "event: empty-event\ndata: \n\n"),
    ],
)
def test_serialize_to_sse_event(event_label: str, event_data: str, expected: str) -> None:
    result = serialize_to_sse_event(event_label, event_data)
    assert result == expected


class TestTokenEstimation:
    def test_estimate_tokens_from_strings(self):
        """Test exact token estimation for strings using o3 model."""
        # Empty input returns 0
        assert estimate_tokens_from_strings(strings=[], model=SESSION_SUMMARIES_SYNC_MODEL) == 0
        # Test with exact token count for o3 model
        result = estimate_tokens_from_strings(
            strings=["Hello world", "Test content"], model=SESSION_SUMMARIES_SYNC_MODEL
        )
        assert result == 4  # Exact token count for these strings with o3 model

    def test_estimate_tokens_from_template_files(self):
        """Test token estimation for template files with data injection."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".djt", delete=False) as f:
            f.write("Prompt: {{ SESSION_SUMMARIES }}")
            f.flush()
            template_path = Path(f.name)

            try:
                # Template alone has exactly 8 tokens with o3 model
                template_only = estimate_tokens_from_template_files(
                    template_paths=[template_path], model=SESSION_SUMMARIES_SYNC_MODEL
                )
                assert template_only == 8
                # With injected data, token count is sum of template + data
                data_to_inject = ["Summary 1", "Summary 2"]
                with_data = estimate_tokens_from_template_files(
                    template_paths=[template_path], data_to_inject=data_to_inject, model=SESSION_SUMMARIES_SYNC_MODEL
                )
                assert with_data == 14  # 8 (template) + 6 (data) = 14 tokens
            finally:
                template_path.unlink()
        # Non-existent file raises FileNotFoundError
        with pytest.raises(FileNotFoundError):
            estimate_tokens_from_template_files(
                template_paths=[Path("/nonexistent.djt")], model=SESSION_SUMMARIES_SYNC_MODEL
            )
