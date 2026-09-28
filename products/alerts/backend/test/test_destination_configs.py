from dataclasses import replace
from typing import Any

import pytest

from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES
from posthog.cdp.templates.fixtures import template_pagerduty

from products.alerts.backend.facade.contracts import (
    AlertDestinationAction,
    AlertDestinationData,
    AlertIncidentRole,
    DestinationType,
    EventKindSpec,
    PagerDutySeverity,
)
from products.alerts.backend.logic.destination_configs import (
    DESTINATION_SPECS,
    build_alert_destination_config,
    slack_blocks,
    teams_text,
)

DEFAULT_SPEC = EventKindSpec(
    event_id="$insight_alert_firing",
    display_kind="firing",
    incident_role=AlertIncidentRole.OPEN,
    header="Insight alert firing",
    details=(("Threshold", "30"),),
    primary_action_url="https://example.com/insight",
    primary_action_label="View insight",
    webhook_body={},
)

MULTI_DETAIL_SPEC = EventKindSpec(
    event_id="$insight_alert_broken",
    display_kind="broken",
    incident_role=AlertIncidentRole.CHECK_FAILURE,
    header="Insight alert broken",
    details=(("Reason", "5 consecutive check failures."), ("Last error", "Query is too expensive.")),
    primary_action_url="https://example.com/insight",
    primary_action_label="View insight",
    webhook_body={},
)

PROSE_SPEC = EventKindSpec(
    event_id="$insight_alert_firing",
    display_kind="firing",
    incident_role=AlertIncidentRole.OPEN,
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

    def test_slack_renders_one_line_per_detail(self) -> None:
        blocks = slack_blocks(MULTI_DETAIL_SPEC, context_elements=())

        section = next(b for b in blocks if b["type"] == "section")
        assert section["text"]["text"] == (
            "*Reason:* 5 consecutive check failures.\n*Last error:* Query is too expensive."
        )

    def test_teams_separates_details_with_one_blank_line(self) -> None:
        text = teams_text(MULTI_DETAIL_SPEC)

        assert "**Reason:** 5 consecutive check failures.\n\n**Last error:** Query is too expensive." in text
        # An Adaptive Card paragraph break is exactly one blank line; stacked ones render as gaps.
        assert "\n\n\n" not in text
        # Every asterisk belongs to a `**` pair. A Slack single-asterisk bold renders literally here.
        assert "*" not in text.replace("**", "")

    def test_defaults_render_single_button_and_details_only(self) -> None:
        blocks = slack_blocks(DEFAULT_SPEC, context_elements=())
        actions = next(b for b in blocks if b["type"] == "actions")
        assert len(actions["elements"]) == 1
        assert teams_text(DEFAULT_SPEC) == (
            "**Insight alert firing**\n\n**Threshold:** 30\n\n[View insight](https://example.com/insight)"
        )


_TEMPLATES_BY_ID = {template.id: template for template in HOG_FUNCTION_TEMPLATES}

_TEMPLATE_IDS_DEFINED_IN_NODEJS = {"template-slack", "template-webhook", "template-pagerduty"}

_STAND_IN_TEMPLATES_BY_ID = {template_pagerduty.id: template_pagerduty}

_DESTINATION_DATA: dict[DestinationType, AlertDestinationData] = {
    DestinationType.DISCORD: {"type": DestinationType.DISCORD, "webhook_url": "https://discord.example.com/hook"},
    DestinationType.TEAMS: {"type": DestinationType.TEAMS, "webhook_url": "https://teams.example.com/hook"},
    DestinationType.PAGERDUTY: {
        "type": DestinationType.PAGERDUTY,
        "pagerduty_routing_key": "abcdef0123456789abcdef0123456789",
        "pagerduty_severity": PagerDutySeverity.WARNING,
    },
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
        template_id = DESTINATION_SPECS[destination_type].template_id
        template = _TEMPLATES_BY_ID.get(template_id) or _STAND_IN_TEMPLATES_BY_ID[template_id]
        data = _DESTINATION_DATA[destination_type]
        config = build_alert_destination_config(
            spec=DEFAULT_SPEC,
            alert_id="alert-1",
            alert_name="Signups",
            data=data,
            slack_context_elements=(),
        )

        stored_inputs = _inputs_a_hog_function_would_keep(template, config.payload["inputs"])

        destination_spec = DESTINATION_SPECS[destination_type]
        assert destination_spec.read(stored_inputs) == {
            key: value for key, value in data.items() if key not in destination_spec.write_only_fields
        }

    @pytest.mark.parametrize(
        "incident_role,event_action,dedup_key",
        [
            (AlertIncidentRole.OPEN, "trigger", "posthog-alert-{event.properties.alert_id}"),
            (AlertIncidentRole.RESOLVE, "resolve", "posthog-alert-{event.properties.alert_id}"),
            (
                AlertIncidentRole.CHECK_FAILURE,
                "trigger",
                "posthog-alert-{event.properties.alert_id}-check-failure",
            ),
        ],
    )
    def test_pagerduty_event_action_and_dedup_key_follow_the_incident_role(
        self, incident_role: AlertIncidentRole, event_action: str, dedup_key: str
    ) -> None:
        config = build_alert_destination_config(
            spec=replace(DEFAULT_SPEC, incident_role=incident_role),
            alert_id="alert-1",
            alert_name="Signups",
            data=_DESTINATION_DATA[DestinationType.PAGERDUTY],
            slack_context_elements=(),
        )

        inputs = config.payload["inputs"]
        assert inputs["event_action"]["value"] == event_action
        assert inputs["dedup_key"]["value"] == dedup_key
        assert inputs["severity"]["value"] == "warning"

    def test_pagerduty_refuses_an_event_kind_without_an_incident_role(self) -> None:
        with pytest.raises(ValueError, match="has no incident_role"):
            build_alert_destination_config(
                spec=replace(DEFAULT_SPEC, incident_role=None),
                alert_id="alert-1",
                alert_name="Signups",
                data=_DESTINATION_DATA[DestinationType.PAGERDUTY],
                slack_context_elements=(),
            )

    @pytest.mark.parametrize(
        "spec,summary,links",
        [
            (
                DEFAULT_SPEC,
                "Insight alert firing: 30",
                [{"href": "https://example.com/insight", "text": "View insight"}],
            ),
            (
                PROSE_SPEC,
                "Insight alert firing",
                [
                    {"href": "https://example.com/insight", "text": "View insight"},
                    {"href": "https://example.com/alert", "text": "Manage alert"},
                ],
            ),
        ],
    )
    def test_pagerduty_summary_names_the_breach_and_links_back_to_posthog(
        self, spec: EventKindSpec, summary: str, links: list[dict[str, str]]
    ) -> None:
        config = build_alert_destination_config(
            spec=spec,
            alert_id="alert-1",
            alert_name="Signups",
            data=_DESTINATION_DATA[DestinationType.PAGERDUTY],
            slack_context_elements=(),
        )

        assert config.payload["inputs"]["summary"]["value"] == summary
        assert config.payload["inputs"]["links"]["value"] == links

    def test_slack_channel_name_shapes_the_hog_function_name_and_is_never_stored_in_inputs(self) -> None:
        data: AlertDestinationData = {
            "type": DestinationType.SLACK,
            "slack_workspace_id": 42,
            "slack_channel_id": "C123",
            "slack_channel_name": "eng",
        }
        config = build_alert_destination_config(
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
