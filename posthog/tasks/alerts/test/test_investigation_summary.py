import pytest
from unittest.mock import MagicMock

from posthog.tasks.alerts.utils import (
    INVESTIGATION_SUMMARY_TEASER_MAX_CHARS,
    chat_investigation_summary,
    investigation_summary_teaser,
)

from products.alerts.backend.models import AlertConfiguration


@pytest.mark.parametrize(
    "input,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("Traffic doubled after a marketing campaign launch.", "Traffic doubled after a marketing campaign launch."),
        ("  hello  ", "hello."),
        (
            "- `signup_count` rose to **240** at _10:00 UTC_\n- Most new users came from [the docs](https://example.com)",
            "signup_count rose to 240 at 10:00 UTC. Most new users came from the docs.",
        ),
        ("Latency rose for <none> service.", "Latency rose for <none> service."),
    ],
)
def test_investigation_summary_teaser_basic(input: str | None, expected: str | None) -> None:
    assert investigation_summary_teaser(input) == expected


def test_investigation_summary_teaser_clips_long_text_with_ellipsis() -> None:
    text = "x" * (INVESTIGATION_SUMMARY_TEASER_MAX_CHARS + 50)
    clipped = investigation_summary_teaser(text)
    assert clipped is not None
    assert len(clipped) == INVESTIGATION_SUMMARY_TEASER_MAX_CHARS
    assert clipped.endswith("…")


def test_investigation_summary_teaser_clips_on_sentence_boundary() -> None:
    text = "All systems nominal here. " * 40  # > the cap, sentence ends past the midpoint
    clipped = investigation_summary_teaser(text)
    assert clipped is not None
    # Clips on a full sentence (not mid-word) and always signals truncation with an ellipsis.
    assert clipped.endswith("…")
    body = clipped.removesuffix(" …")
    assert body.endswith(".")
    assert text.startswith(body)


def test_chat_investigation_summary_keeps_metrics_summaries_whole() -> None:
    alert = MagicMock(spec=AlertConfiguration)
    alert.detector_config = None
    summary = "http_requests_total *rose* on <none> " + "x " * 400

    assert chat_investigation_summary(alert, summary) == summary
