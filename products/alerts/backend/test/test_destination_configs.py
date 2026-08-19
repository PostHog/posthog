import pytest

from products.alerts.backend.destination_configs import (
    AlertDestinationAction,
    AlertDestinationData,
    DestinationType,
    EventKindSpec,
    build_alert_destination_config,
    read_alert_destination_data,
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


def _build_payload(data: AlertDestinationData) -> dict:
    config = build_alert_destination_config(
        team=None,
        spec=DEFAULT_SPEC,
        alert_id="alert-1",
        alert_name="Alert",
        data=data,
        slack_context_elements=(),
    )
    return config.payload


class TestDestinationDataSurvivesTheHogFunctionRoundTrip:
    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(
                {"type": DestinationType.SLACK, "slack_workspace_id": 7, "slack_channel_id": "C1"}, id="slack"
            ),
            pytest.param({"type": DestinationType.WEBHOOK, "webhook_url": "https://example.com/hook"}, id="webhook"),
            pytest.param({"type": DestinationType.DISCORD, "webhook_url": "https://example.com/discord"}, id="discord"),
            pytest.param({"type": DestinationType.TEAMS, "webhook_url": "https://example.com/teams"}, id="teams"),
        ],
    )
    def test_read_recovers_everything_build_was_given(self, data: AlertDestinationData) -> None:
        payload = _build_payload(data)

        assert read_alert_destination_data(destination_type=data["type"], inputs=payload["inputs"]) == data

    def test_build_puts_slack_channel_name_in_the_name_so_read_cannot_recover_it(self) -> None:
        payload = _build_payload(
            {
                "type": DestinationType.SLACK,
                "slack_workspace_id": 7,
                "slack_channel_id": "C1",
                "slack_channel_name": "alerts",
            }
        )

        assert "Slack #alerts" in payload["name"]
        assert read_alert_destination_data(destination_type=DestinationType.SLACK, inputs=payload["inputs"]) == {
            "type": DestinationType.SLACK,
            "slack_workspace_id": 7,
            "slack_channel_id": "C1",
        }
