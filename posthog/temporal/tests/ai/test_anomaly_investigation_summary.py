from posthog.temporal.ai.anomaly_investigation.workflow import MAX_SUMMARY_CHARS, _truncate_summary


def test_truncate_summary_returns_none_for_empty() -> None:
    assert _truncate_summary(None) is None
    assert _truncate_summary("") is None
    assert _truncate_summary("   ") is None


def test_truncate_summary_passes_short_text_through() -> None:
    text = "Traffic doubled after a marketing campaign launch."
    assert _truncate_summary(text) == text


def test_truncate_summary_clips_long_text_with_ellipsis() -> None:
    text = "x" * (MAX_SUMMARY_CHARS + 50)
    clipped = _truncate_summary(text)
    assert clipped is not None
    assert len(clipped) == MAX_SUMMARY_CHARS
    assert clipped.endswith("…")


def test_truncate_summary_strips_whitespace_before_clipping() -> None:
    assert _truncate_summary("  hello  ") == "hello"
