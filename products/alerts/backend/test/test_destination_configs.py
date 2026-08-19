import pytest

from products.alerts.backend.destination_configs import (
    AlertDestinationAction,
    EventKindSpec,
    redact_webhook_url,
    slack_blocks,
    teams_text,
)

DEFAULT_SPEC = EventKindSpec(
    event_id="$insight_alert_firing",
    display_kind="firing",
    header="Insight alert firing",
    details=(("Threshold", "30"),),
    primary_action_url="https://example.com/insight",
    primary_action_label="View insight",
    webhook_body={},
)

PROSE_SPEC = EventKindSpec(
    event_id="$insight_alert_firing",
    display_kind="firing",
    header="Insight alert firing",
    details=(),
    primary_action_url="https://example.com/insight",
    primary_action_label="View insight",
    webhook_body={},
    intro_lines=("Pageviews is 42, breaching 30", "Signups is 7, breaching 5"),
    additional_actions=(AlertDestinationAction(url="https://example.com/alert", label="Manage alert"),),
)


class TestSpecVocabularyRendering:
    def test_slack_renders_intro_lines_and_additional_actions(self) -> None:
        blocks = slack_blocks(PROSE_SPEC, context_elements=("Project: PostHog", "Alert ID: alert-1"))

        section = next(b for b in blocks if b["type"] == "section")
        assert "Pageviews is 42, breaching 30\nSignups is 7, breaching 5" in section["text"]["text"]

        context = next(b for b in blocks if b["type"] == "context")
        assert context["elements"] == [
            {"type": "mrkdwn", "text": "Project: PostHog"},
            {"type": "mrkdwn", "text": "Alert ID: alert-1"},
        ]

        actions = next(b for b in blocks if b["type"] == "actions")
        assert [(e["url"], e["text"]["text"]) for e in actions["elements"]] == [
            ("https://example.com/insight", "View insight"),
            ("https://example.com/alert", "Manage alert"),
        ]

    def test_teams_renders_intro_lines_and_additional_actions(self) -> None:
        text = teams_text(PROSE_SPEC)
        assert "Pageviews is 42, breaching 30" in text
        assert "[View insight](https://example.com/insight) · [Manage alert](https://example.com/alert)" in text

    def test_defaults_render_single_button_and_details_only(self) -> None:
        blocks = slack_blocks(DEFAULT_SPEC, context_elements=())
        actions = next(b for b in blocks if b["type"] == "actions")
        assert len(actions["elements"]) == 1
        assert teams_text(DEFAULT_SPEC) == (
            "**Insight alert firing**\n\n**Threshold:** 30\n\n[View insight](https://example.com/insight)"
        )


class TestRedactWebhookUrl:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://hooks.slack.com/services/T0/B0/tok", "https://hooks.slack.com/…"),
            # Defense in depth: creation rejects embedded credentials, but redaction must not
            # echo them if one ever reaches the read path.
            ("https://token:secret@hooks.example.com/path", "https://hooks.example.com/…"),
            ("https://hooks.example.com:8443/path?key=v", "https://hooks.example.com:8443/…"),
            ("https://[2001:db8::1]:9000/path", "https://[2001:db8::1]:9000/…"),
            ("not-a-url", "(hidden)"),
            ("https://example.com:99999/path", "(hidden)"),
            ("", "(hidden)"),
        ],
    )
    def test_keeps_only_scheme_and_host(self, url: str, expected: str) -> None:
        assert redact_webhook_url(url) == expected
