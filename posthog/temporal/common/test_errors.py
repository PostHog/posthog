import pytest

from posthog.temporal.common.errors import MAX_ERROR_MESSAGE_CHARS, MAX_ERROR_TRACE_CHARS, truncate_for_temporal_payload


@pytest.mark.parametrize(
    "value,limit,expected",
    [
        # Short values pass through unchanged
        ("", 10, ""),
        ("short", 10, "short"),
        ("exactly10!", 10, "exactly10!"),
        # Long values are truncated with a diagnostic marker
        ("a" * 20, 10, "aaaaaaaaaa… (truncated, original 20 chars)"),
        # Limit of 0 is treated as "no content"
        ("anything", 0, "… (truncated, original 8 chars)"),
    ],
)
def test_truncate_for_temporal_payload(value, limit, expected):
    assert truncate_for_temporal_payload(value, limit) == expected


def test_default_limits_fit_under_temporal_payload_limit():
    # Temporal's hard limit is 2 MiB for the whole payload — activity metadata, input ref,
    # envelope framing, and our error strings all share that budget. Assert our error strings
    # fit inside 1 MiB (worst-case UTF-8: 4 bytes/char) to leave headroom for everything else.
    worst_case_error_bytes = (MAX_ERROR_MESSAGE_CHARS + MAX_ERROR_TRACE_CHARS) * 4
    assert worst_case_error_bytes < 1 * 1024 * 1024
