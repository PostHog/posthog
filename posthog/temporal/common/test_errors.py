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
    # Temporal's hard gRPC payload limit is 2 MiB; keep message + trace well under
    # so metadata and framing still fit.
    assert MAX_ERROR_MESSAGE_CHARS + MAX_ERROR_TRACE_CHARS < 2 * 1024 * 1024
