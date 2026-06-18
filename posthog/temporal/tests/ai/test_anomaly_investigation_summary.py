import pytest

from posthog.temporal.ai.anomaly_investigation.workflow import MAX_SUMMARY_CHARS, _truncate_summary


@pytest.mark.parametrize(
    "input,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("Traffic doubled after a marketing campaign launch.", "Traffic doubled after a marketing campaign launch."),
        ("  hello  ", "hello"),
    ],
)
def test_truncate_summary_basic(input, expected) -> None:
    assert _truncate_summary(input) == expected


def test_truncate_summary_clips_long_text_with_ellipsis() -> None:
    text = "x" * (MAX_SUMMARY_CHARS + 50)
    clipped = _truncate_summary(text)
    assert clipped is not None
    assert len(clipped) == MAX_SUMMARY_CHARS
    assert clipped.endswith("…")
