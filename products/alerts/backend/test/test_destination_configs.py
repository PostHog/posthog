from parameterized import parameterized

from products.alerts.backend.destination_configs import (
    AlertDestinationAction,
    EventKindSpec,
    is_microsoft_teams_webhook_url,
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


class TestMicrosoftTeamsWebhookUrl:
    @parameterized.expand(
        [
            (
                "logic_apps",
                "https://prod-25.westeurope.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=x",
            ),
            ("incoming_webhook", "https://acme.webhook.office.com/webhookb2/guid@guid/IncomingWebhook/hash/guid"),
            ("power_automate", "https://europe.powerautomate.com/manual/paths/invoke"),
            ("flow", "https://prod-01.flow.microsoft.com/manual/paths/invoke"),
            (
                "power_platform_environment",
                "https://acme.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/abc",
            ),
        ]
    )
    def test_accepts_microsoft_webhook_url(self, _name: str, url: str) -> None:
        assert is_microsoft_teams_webhook_url(url) is True

    @parameterized.expand(
        [
            # Both hostnames are registrable by anyone and satisfy the unescaped-dot patterns in the
            # CDP Teams template. They must not satisfy these.
            ("lookalike_power_automate", "https://evilpowerautomate.com/x"),
            ("lookalike_flow", "https://aaaflow-microsoft.com/y"),
            ("suffix_in_path", "https://evil.example.com/logic.azure.com/workflows/abc"),
            ("subdomain_prefix", "https://logic.azure.com.evil.example.com/workflows/abc"),
            ("http_scheme", "http://prod-25.westeurope.logic.azure.com/workflows/abc/triggers/manual/paths/invoke"),
            (
                "unexpected_port",
                "https://prod-25.westeurope.logic.azure.com:8443/workflows/abc/triggers/manual/paths/invoke",
            ),
            ("logic_apps_without_trigger_path", "https://prod-25.westeurope.logic.azure.com/workflows/abc"),
            ("connector_without_incoming_webhook", "https://acme.webhook.office.com/webhookb2/guid"),
            ("wrong_path", "https://acme.webhook.office.com/something-else/guid"),
            (
                "authority_confusion",
                "https://prod-25.westeurope.logic.azure.com\\@evil.example.com/workflows/abc/triggers/manual/paths/invoke",
            ),
            ("not_a_url", "definitely not a url"),
            ("empty", ""),
        ]
    )
    def test_rejects_non_teams_url(self, _name: str, url: str) -> None:
        assert is_microsoft_teams_webhook_url(url) is False
