from typing import Any

import pytest

from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES

from products.alerts.backend.destination_configs import (
    DESTINATION_SPECS,
    AlertDestinationAction,
    AlertDestinationData,
    DestinationType,
    EventKindSpec,
    build_alert_destination_config,
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


_TEMPLATES_BY_ID = {template.id: template for template in HOG_FUNCTION_TEMPLATES}

_TEMPLATE_IDS_DEFINED_IN_NODEJS = {"template-slack", "template-webhook"}

_DESTINATION_DATA: dict[DestinationType, AlertDestinationData] = {
    DestinationType.DISCORD: {"type": DestinationType.DISCORD, "webhook_url": "https://discord.example.com/hook"},
    DestinationType.TEAMS: {"type": DestinationType.TEAMS, "webhook_url": "https://teams.example.com/hook"},
}


def _inputs_a_hog_function_would_keep(template: Any, inputs: dict[str, Any]) -> dict[str, Any]:
    return {entry["key"]: inputs.get(entry["key"]) for entry in template.inputs_schema or [] if not entry.get("secret")}


class TestDestinationTemplateContract:
    def test_the_templates_defined_outside_python_are_the_ones_we_expect(self) -> None:
        unreachable = {spec.template_id for spec in DESTINATION_SPECS.values()} - set(_TEMPLATES_BY_ID)

        assert unreachable == _TEMPLATE_IDS_DEFINED_IN_NODEJS

    @pytest.mark.parametrize("destination_type", list(_DESTINATION_DATA))
    def test_a_config_read_back_from_the_inputs_a_template_keeps_equals_the_config_built(
        self, destination_type: DestinationType
    ) -> None:
        template = _TEMPLATES_BY_ID[DESTINATION_SPECS[destination_type].template_id]
        data = _DESTINATION_DATA[destination_type]
        config = build_alert_destination_config(
            team=None,
            spec=DEFAULT_SPEC,
            alert_id="alert-1",
            alert_name="Signups",
            data=data,
            slack_context_elements=(),
        )

        stored_inputs = _inputs_a_hog_function_would_keep(template, config.payload["inputs"])

        assert DESTINATION_SPECS[destination_type].read(stored_inputs) == data

    def test_slack_channel_name_shapes_the_hog_function_name_and_is_never_stored_in_inputs(self) -> None:
        data: AlertDestinationData = {
            "type": DestinationType.SLACK,
            "slack_workspace_id": 42,
            "slack_channel_id": "C123",
            "slack_channel_name": "eng",
        }
        config = build_alert_destination_config(
            team=None,
            spec=DEFAULT_SPEC,
            alert_id="alert-1",
            alert_name="Signups",
            data=data,
            slack_context_elements=(),
        )

        assert config.payload["name"].endswith("Slack #eng")
        assert DESTINATION_SPECS[DestinationType.SLACK].read(config.payload["inputs"]) == {
            "type": DestinationType.SLACK,
            "slack_workspace_id": 42,
            "slack_channel_id": "C123",
        }
