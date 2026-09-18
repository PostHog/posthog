from typing import Any

import pytest

from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES
from posthog.cdp.templates.fixtures import template_pagerduty

from products.alerts.backend.facade.contracts import (
    AlertDestinationAction,
    AlertDestinationData,
    AlertDestinationValidationError,
    DestinationType,
    EventKindSpec,
    IncidentAction,
)
from products.alerts.backend.logic.destination_configs import (
    DESTINATION_SPECS,
    build_alert_destination_config,
    destination_handles_event_kind,
    slack_blocks,
    teams_text,
    validate_destination_data,
)
from products.alerts.backend.logic.destinations import stored_inputs

DEFAULT_SPEC = EventKindSpec(
    event_id="$insight_alert_firing",
    display_kind="firing",
    header="Insight alert firing",
    details=(("Threshold", "30"),),
    primary_action_url="https://example.com/insight",
    primary_action_label="View insight",
    webhook_body={},
    incident_action=IncidentAction.TRIGGER,
)

RESOLVED_SPEC = EventKindSpec(
    event_id="$insight_alert_resolved",
    display_kind="resolved",
    header="Insight alert resolved",
    details=(("Current value", "12"),),
    primary_action_url="https://example.com/insight",
    primary_action_label="View insight",
    webhook_body={},
    incident_action=IncidentAction.RESOLVE,
)

MULTI_DETAIL_SPEC = EventKindSpec(
    event_id="$insight_alert_broken",
    display_kind="broken",
    header="Insight alert broken",
    details=(("Reason", "5 consecutive check failures."), ("Last error", "Query is too expensive.")),
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


_PYTHON_TEMPLATE_IDS = {template.id for template in HOG_FUNCTION_TEMPLATES}

_TEMPLATE_IDS_DEFINED_IN_NODEJS = {"template-slack", "template-webhook", "template-pagerduty"}

# The PagerDuty template lives in nodejs; its fixture stand-in tracks the nodejs inputs schema.
_TEMPLATES_BY_ID = {template.id: template for template in (*HOG_FUNCTION_TEMPLATES, template_pagerduty)}

PAGERDUTY_ROUTING_KEY = "0123456789abcdef0123456789abcdef"

_DESTINATION_DATA: dict[DestinationType, AlertDestinationData] = {
    DestinationType.DISCORD: {"type": DestinationType.DISCORD, "webhook_url": "https://discord.example.com/hook"},
    DestinationType.TEAMS: {"type": DestinationType.TEAMS, "webhook_url": "https://teams.example.com/hook"},
    DestinationType.PAGERDUTY: {
        "type": DestinationType.PAGERDUTY,
        "pagerduty_routing_key": PAGERDUTY_ROUTING_KEY,
        "pagerduty_severity": "error",
        "pagerduty_region": "eu",
    },
}


def _inputs_the_read_path_sees(template: Any, inputs: dict[str, Any]) -> dict[str, Any]:
    # A saved HogFunction splits its inputs by the template schema: plain ones stay in
    # `inputs`, secret ones move to `encrypted_inputs`. The read path merges them back.
    plain = {entry["key"]: inputs.get(entry["key"]) for entry in template.inputs_schema if not entry.get("secret")}
    secret = {entry["key"]: inputs.get(entry["key"]) for entry in template.inputs_schema if entry.get("secret")}
    return stored_inputs(plain, secret)


class TestDestinationTemplateContract:
    def test_the_templates_defined_outside_python_are_the_ones_we_expect(self) -> None:
        unreachable = {spec.template_id for spec in DESTINATION_SPECS.values()} - _PYTHON_TEMPLATE_IDS

        assert unreachable == _TEMPLATE_IDS_DEFINED_IN_NODEJS

    @pytest.mark.parametrize("destination_type", list(_DESTINATION_DATA))
    def test_a_config_read_back_from_the_inputs_a_template_keeps_equals_the_config_built(
        self, destination_type: DestinationType
    ) -> None:
        template = _TEMPLATES_BY_ID[DESTINATION_SPECS[destination_type].template_id]
        data = _DESTINATION_DATA[destination_type]
        config = build_alert_destination_config(
            spec=DEFAULT_SPEC,
            alert_id="alert-1",
            alert_name="Signups",
            data=data,
            slack_context_elements=(),
        )

        assert (
            DESTINATION_SPECS[destination_type].read(_inputs_the_read_path_sees(template, config.payload["inputs"]))
            == data
        )

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


def _pagerduty_config(spec: EventKindSpec, data: AlertDestinationData | None = None) -> dict[str, Any]:
    config = build_alert_destination_config(
        spec=spec,
        alert_id="alert-1",
        alert_name="Signups",
        data=data or _DESTINATION_DATA[DestinationType.PAGERDUTY],
        slack_context_elements=(),
    )
    return config.payload


class TestPagerDutyDestination:
    def test_firing_and_resolved_address_the_same_incident(self) -> None:
        firing = _pagerduty_config(DEFAULT_SPEC)["inputs"]
        resolved = _pagerduty_config(RESOLVED_SPEC)["inputs"]

        assert firing["event_action"]["value"] == "trigger"
        assert resolved["event_action"]["value"] == "resolve"
        assert firing["dedup_key"]["value"] == resolved["dedup_key"]["value"] == "posthog-alert-alert-1"
        assert firing["routing_key"]["value"] == PAGERDUTY_ROUTING_KEY
        assert firing["region"]["value"] == "eu"
        assert firing["severity"]["value"] == "error"
        assert firing["summary"]["value"] == "Insight alert firing: 30"
        assert firing["custom_details"]["value"] == {"Threshold": "30"}
        assert firing["links"]["value"] == [{"href": "https://example.com/insight", "text": "View insight"}]
        assert firing["client_url"]["value"] == "https://example.com/insight"

    def test_severity_and_region_default_when_a_caller_leaves_them_out(self) -> None:
        inputs = _pagerduty_config(
            DEFAULT_SPEC, {"type": DestinationType.PAGERDUTY, "pagerduty_routing_key": PAGERDUTY_ROUTING_KEY}
        )["inputs"]

        assert inputs["severity"]["value"] == "critical"
        assert inputs["region"]["value"] == "us"

    def test_the_name_and_the_read_response_keep_only_the_tail_of_the_key(self) -> None:
        payload = _pagerduty_config(DEFAULT_SPEC)

        assert payload["name"].endswith("→ PagerDuty ••••cdef")
        redacted = DESTINATION_SPECS[DestinationType.PAGERDUTY].redact(_DESTINATION_DATA[DestinationType.PAGERDUTY])
        assert redacted["pagerduty_routing_key"] == "••••cdef"
        assert PAGERDUTY_ROUTING_KEY not in str(redacted)

    def test_only_kinds_that_trigger_or_resolve_an_incident_are_sent(self) -> None:
        assert destination_handles_event_kind(DestinationType.PAGERDUTY, DEFAULT_SPEC)
        assert not destination_handles_event_kind(DestinationType.PAGERDUTY, MULTI_DETAIL_SPEC)
        assert destination_handles_event_kind(DestinationType.TEAMS, MULTI_DETAIL_SPEC)

        with pytest.raises(ValueError, match="nothing to send"):
            _pagerduty_config(MULTI_DETAIL_SPEC)

    def test_a_config_without_the_key_reads_as_unreadable_rather_than_as_a_duplicate(self) -> None:
        masked = {"routing_key": {"secret": True}, "severity": {"value": "critical"}, "region": {"value": "us"}}

        assert DESTINATION_SPECS[DestinationType.PAGERDUTY].read(masked) == {"type": DestinationType.PAGERDUTY}

    @pytest.mark.parametrize(
        "data,field,message",
        [
            (
                {"type": DestinationType.PAGERDUTY, "pagerduty_routing_key": "too-short"},
                "pagerduty_routing_key",
                "Enter the 32-character integration key of a PagerDuty Events API v2 integration.",
            ),
            (
                {
                    "type": DestinationType.PAGERDUTY,
                    "pagerduty_routing_key": PAGERDUTY_ROUTING_KEY,
                    "pagerduty_severity": "urgent",
                },
                "pagerduty_severity",
                "Choose a severity: critical, error, warning, info.",
            ),
            (
                {
                    "type": DestinationType.PAGERDUTY,
                    "pagerduty_routing_key": PAGERDUTY_ROUTING_KEY,
                    "pagerduty_region": "apac",
                },
                "pagerduty_region",
                "Choose a region: us, eu.",
            ),
        ],
    )
    def test_validation_rejects_a_malformed_pagerduty_payload(
        self, data: AlertDestinationData, field: str, message: str
    ) -> None:
        with pytest.raises(AlertDestinationValidationError) as error:
            validate_destination_data(data, allowed_destination_types=(DestinationType.PAGERDUTY,))

        assert error.value.field == field
        assert error.value.message == message
