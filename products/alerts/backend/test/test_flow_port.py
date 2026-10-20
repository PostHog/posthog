import base64
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts.backend.facade.contracts import FlowDrafts, FlowPort, FlowPortProblem, NamedAlert
from products.alerts.backend.facade.destinations import create_flow_drafts, flow_ports
from products.alerts.backend.logic.flow_port import PlaceholderLog, rewrite_template
from products.alerts_platform.backend.facade.contracts import AlertEventKind
from products.alerts_platform.backend.facade.testing import create_configuration
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hog_functions.hog_function_revision import HogFunctionRevision
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.workflows.backend.facade.testing import count_workflows_for_test, stored_workflow_for_test

ALERT_ID = "01936a2e-0000-7000-8000-0000000000aa"
TRANSITIONS = {
    "$logs_alert_firing": AlertEventKind.FIRING,
    "$logs_alert_resolved": AlertEventKind.RESOLVED,
    "$logs_alert_errored": AlertEventKind.ERRORED,
    "$logs_alert_auto_disabled": AlertEventKind.BROKEN,
}
EVENT_IDS = [*TRANSITIONS, "$logs_alert_incident_opened"]
# Prefixed and unpadded, both of which a workflow webhook step accepts.
SIGNING_SECRET = "whsec_" + base64.b64encode(b"not-a-real-secret-it-is-32-bytes").decode().rstrip("=")
STOCK_BODY = {"type": "logs_alert.firing"}
WEBHOOK_INPUTS: dict[str, Any] = {
    "url": {"value": "https://hooks.example.com/hook"},
    "method": {"value": "POST"},
    "body": {"value": STOCK_BODY},
}


def _webhook_template(*, signing_secret_is_secret: bool) -> dict[str, Any]:
    return {
        "id": "template-webhook",
        "name": "HTTP Webhook",
        "description": "",
        "type": "destination",
        "status": "stable",
        "free": True,
        "category": [],
        "icon_url": "",
        "code_language": "hog",
        "code": "return inputs.url",
        "inputs_schema": [
            *({"key": key, "type": "string", "label": key} for key in ("url", "method", "body")),
            {"key": "signing_secret", "type": "string", "label": "Secret", "secret": signing_secret_is_secret},
        ],
    }


class _FlowPortCase(APIBaseTest):
    source_kind = "logs"

    def setUp(self) -> None:
        super().setUp()
        with team_scope(self.team.id):
            self.configuration = create_configuration(
                team=self.team,
                name="API errors",
                source_kind=self.source_kind,
                check_interval_minutes=5,
                legacy_configuration_id=ALERT_ID,
            )

    def _function(
        self,
        event: str = "$logs_alert_firing",
        *,
        template_id: str = "template-webhook",
        inputs: dict[str, Any] = WEBHOOK_INPUTS,
        secret: str | None = None,
        extra_properties: tuple[dict[str, Any], ...] = (),
        event_properties: tuple[dict[str, Any], ...] = (),
        masking: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name="Alert destination",
            type="internal_destination",
            template_id=template_id,
            enabled=enabled,
            inputs={**inputs, **({"signing_secret": {"value": secret}} if secret else {})},
            inputs_schema=[
                *({"key": key, "type": "string"} for key in inputs),
                {"key": "signing_secret", "type": "string", "secret": True},
            ],
            hog="return event",
            masking=masking,
            filters={
                "source": "internal-events",
                "events": [
                    {
                        "id": event,
                        "type": "events",
                        **({"properties": list(event_properties)} if event_properties else {}),
                    }
                ],
                "properties": [
                    {"key": "alert_id", "value": ALERT_ID, "operator": "exact", "type": "event"},
                    *extra_properties,
                ],
            },
        )

    def _edit(self, function: HogFunction, **changes: Any) -> None:
        HogFunctionRevision.objects.for_team(self.team.id).create(
            team=self.team,
            hog_function=function,
            version=1,
            content={
                "hog": function.hog,
                "inputs_schema": function.inputs_schema,
                "inputs": function.inputs,
                "filters": function.filters,
                "mappings": function.mappings,
                "masking": function.masking,
            },
        )
        HogFunction.objects.filter(pk=function.pk).update(version=2, **changes)

    def _ports(self, alert_id: str = ALERT_ID) -> list[FlowPort]:
        return list(
            flow_ports(
                team_id=self.team.id,
                alerts=[NamedAlert(alert_id=alert_id, name="API errors")],
                allowed_event_ids=EVENT_IDS,
                transition_by_event_id=TRANSITIONS,
            )
        )

    def _customized_webhook(self, masking: dict[str, Any] | None = None) -> HogFunction:
        function = self._function(secret=SIGNING_SECRET, masking=masking)
        self._edit(function, inputs={**(function.inputs or {}), "method": {"value": "PUT"}})
        return function

    def _create(self) -> FlowDrafts:
        return create_flow_drafts(
            team_id=self.team.id,
            alert=NamedAlert(alert_id=ALERT_ID, name="API errors"),
            allowed_event_ids=EVENT_IDS,
            transition_by_event_id=TRANSITIONS,
        )


class TestFlowPorts(_FlowPortCase):
    def test_a_customized_webhook_becomes_one_draft_flow_with_a_step_per_transition(self) -> None:
        firing = self._function(secret=SIGNING_SECRET)
        for event in ("$logs_alert_resolved", "$logs_alert_errored", "$logs_alert_auto_disabled"):
            self._function(event, secret=SIGNING_SECRET)
        disabled_errored_twin = self._function("$logs_alert_errored", secret=SIGNING_SECRET, enabled=False)
        body = {"text": "{event.properties.alert_name}: {event.properties.result_count} at {event.timestamp}"}
        self._edit(firing, inputs={**WEBHOOK_INPUTS, "body": {"value": body}})
        self._function(
            template_id="template-slack", inputs={"slack_workspace": {"value": 1}, "channel": {"value": "C-1"}}
        )

        (port,) = self._ports()

        assert port.issues == ()
        assert port.left_out == (disabled_errored_twin.id,)
        assert port.rewrites == (
            "event.properties.alert_name -> event.properties.source.alert_name",
            "event.properties.result_count -> event.properties.source.result_count",
        )
        assert port.flow is not None
        flow = port.flow
        assert flow["status"] == "draft"
        assert flow["trigger"]["filters"]["events"] == [{"id": "$alert_transition", "type": "events"}]
        assert [(prop["key"], prop["value"]) for prop in flow["trigger"]["filters"]["properties"]] == [
            ("alert_configuration_id", [str(self.configuration.id)]),
            ("transition", ["firing", "resolved", "errored", "broken"]),
        ]
        (branch,) = [action for action in flow["actions"] if action["type"] == "conditional_branch"]
        steps = {action["id"]: action for action in flow["actions"] if action["type"] == "function"}
        branch_targets = {
            edge["index"]: edge["to"]
            for edge in flow["edges"]
            if edge["from"] == branch["id"] and edge["type"] == "branch"
        }
        assert [
            (condition["filters"]["properties"][0]["value"], steps[branch_targets[index]]["config"]["template_id"])
            for index, condition in enumerate(branch["config"]["conditions"])
        ] == [
            (["firing"], "template-webhook"),
            (["resolved"], "template-webhook"),
            (["errored"], "template-webhook"),
            (["broken"], "template-webhook"),
        ]
        firing_inputs = steps["send_firing"]["config"]["inputs"]
        assert firing_inputs["body"]["value"] == {
            "text": "{event.properties.source.alert_name}: {event.properties.source.result_count} at {event.timestamp}"
        }
        assert firing_inputs["signing_secret"]["value"] == SIGNING_SECRET
        assert "not-a-real-secret" not in repr(port)

    @parameterized.expand(
        [
            ("pagerduty_incident", {"event": "$logs_alert_incident_opened"}, FlowPortProblem.EVENT_WITHOUT_TRANSITION),
            (
                "person_placeholder",
                {"inputs": {**WEBHOOK_INPUTS, "body": {"value": {"to": "{person.properties.email}"}}}},
                FlowPortProblem.UNKNOWN_PLACEHOLDER,
            ),
            (
                "short_signing_secret",
                {"secret": base64.b64encode(b"short").decode()},
                FlowPortProblem.INVALID_SIGNING_SECRET,
            ),
            (
                "extra_filter",
                {"extra_properties": ({"key": "service", "value": "api", "operator": "exact", "type": "event"},)},
                FlowPortProblem.EXTRA_FILTERS,
            ),
            (
                "event_level_filter",
                {"event_properties": ({"key": "service", "value": "api", "operator": "exact", "type": "event"},)},
                FlowPortProblem.EXTRA_FILTERS,
            ),
            ("edited_code", {"hog": "fetch(inputs.url)"}, FlowPortProblem.EDITED_CODE),
        ]
    )
    def test_a_destination_a_flow_cannot_carry_is_reported_without_a_flow(
        self, _name: str, setup: dict[str, Any], problem: FlowPortProblem
    ) -> None:
        setup = dict(setup)
        hog = setup.pop("hog", None)
        function = self._function(**{"secret": SIGNING_SECRET, **setup})
        self._edit(
            function, **({"hog": hog} if hog else {"inputs": {**(function.inputs or {}), "method": {"value": "PUT"}}})
        )

        (port,) = self._ports()

        assert port.flow is None
        assert problem in {issue.problem for issue in port.issues}

    @parameterized.expand(
        [
            ("one_step_keeps_its_hash", ("$logs_alert_firing",), "{event.properties.source.alert_id}"),
            ("a_cache_shared_by_transitions_stops_it", ("$logs_alert_firing", "$logs_alert_resolved"), None),
        ]
    )
    def test_masking_moves_to_the_trigger(self, _name: str, events: tuple[str, ...], expected_hash: str | None) -> None:
        masking = {"ttl": 3600, "hash": "{event.properties.alert_id}", "threshold": None}
        for event in events:
            self._function(event, secret=SIGNING_SECRET, masking=masking)

        (port,) = self._ports()

        if expected_hash is None:
            assert port.flow is None
            assert [issue.problem for issue in port.issues] == [FlowPortProblem.MIXED_MASKING]
        else:
            assert port.flow is not None
            assert port.flow["trigger_masking"] == {**masking, "hash": expected_hash}

    def test_an_alert_without_a_platform_configuration_gets_no_flow(self) -> None:
        function = self._function(secret=SIGNING_SECRET)
        other_alert = str(uuid4())
        self._edit(
            function,
            inputs={**WEBHOOK_INPUTS, "method": {"value": "PUT"}},
            filters={
                "source": "internal-events",
                "events": [{"id": "$logs_alert_firing", "type": "events"}],
                "properties": [{"key": "alert_id", "value": other_alert, "operator": "exact", "type": "event"}],
            },
        )

        (port,) = self._ports(other_alert)

        assert port.flow is None
        assert [issue.problem for issue in port.issues] == [FlowPortProblem.NO_PLATFORM_CONFIGURATION]


class TestCreateFlowDrafts(_FlowPortCase):
    def test_a_draft_keeps_its_secret_encrypted_and_its_masking_compiled(self) -> None:
        sync_template_to_db(_webhook_template(signing_secret_is_secret=True))
        function = self._customized_webhook(
            masking={"ttl": 3600, "hash": "{event.properties.alert_id}", "threshold": None}
        )

        drafts = self._create()

        assert drafts.refusal is None
        (workflow_id,) = drafts.workflow_ids
        flow = stored_workflow_for_test(team_id=self.team.id, workflow_id=workflow_id)
        assert (flow.status, flow.origin_product) == ("draft", "alerts")
        (step,) = [action for action in flow.actions if action["type"] == "function"]
        assert "signing_secret" not in step["config"]["inputs"]
        assert flow.encrypted_inputs == {step["id"]: {"signing_secret": {"value": SIGNING_SECRET}}}
        assert flow.trigger_masking is not None and flow.trigger_masking["bytecode"]
        assert HogFunction.objects.get(id=function.id).enabled

    @parameterized.expand(
        [
            ("a_destination_is_stopped", "stopped", "cannot become a workflow"),
            ("the_alert_already_has_workflows", "rerun", "already has workflows"),
            ("the_template_would_store_the_secret_in_plain_text", "plain_secret", "does not keep secret"),
        ]
    )
    def test_nothing_is_created_when_a_draft_is_refused(self, _name: str, case: str, reason: str) -> None:
        sync_template_to_db(_webhook_template(signing_secret_is_secret=case != "plain_secret"))
        self._customized_webhook()
        if case == "stopped":
            self._function("$logs_alert_incident_opened", secret=SIGNING_SECRET)
        if case == "rerun":
            self._create()
        workflows_before = count_workflows_for_test(team_id=self.team.id)

        drafts = self._create()

        assert reason in (drafts.refusal or "")
        assert drafts.workflow_ids == ()
        assert count_workflows_for_test(team_id=self.team.id) == workflows_before


class TestCreateFlowDraftsOnAnInsightAlert(_FlowPortCase):
    source_kind = "insight"

    def test_the_trigger_check_refuses_the_alert(self) -> None:
        sync_template_to_db(_webhook_template(signing_secret_is_secret=True))
        self._customized_webhook()

        drafts = self._create()

        assert "Insight alerts" in (drafts.refusal or "")
        assert count_workflows_for_test(team_id=self.team.id) == 0


class TestRewriteTemplate(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a_reference_in_literal_text_needs_a_person",
                "event.properties.x is {event.properties.x}",
                None,
                "event.properties.x is {event.properties.source.x}",
                ["event.properties.x"],
            ),
            (
                "a_brace_in_a_string_literal",
                "{concat('}', event.properties.a)}",
                None,
                "{concat('}', event.properties.source.a)}",
                [],
            ),
            (
                "a_reference_in_an_f_string_needs_a_person",
                "{f'{event.properties.a}'}",
                None,
                "{f'{event.properties.a}'}",
                ["event.properties.a"],
            ),
            (
                "an_escaped_brace_is_literal",
                r"\{event.properties.x}",
                None,
                r"\{event.properties.x}",
                ["event.properties.x"],
            ),
            (
                "a_dict_inside_an_expression",
                "{ {'a': event.properties.a}['a'] }",
                None,
                "{ {'a': event.properties.source.a}['a'] }",
                [],
            ),
            ("bracket_access", "{event.properties['a b']}", None, "{event.properties.source['a b']}", []),
            ("the_whole_properties_dict", "{event.properties}", None, "{event.properties.source}", []),
            ("a_key_named_like_a_global", "{inputs.event}", None, "{inputs.event}", []),
            (
                "project_and_event_time_keep_their_meaning",
                "{project.url} {event.timestamp}",
                None,
                "{project.url} {event.timestamp}",
                [],
            ),
            (
                "liquid",
                "{{ event.properties.x }} {event.properties.y}",
                "liquid",
                "{{ event.properties.source.x }} {event.properties.y}",
                ["event.properties.y"],
            ),
            ("the_whole_event_differs", "{event}", None, "{event}", ["event"]),
            ("the_event_name_differs", "{event.event}", None, "{event.event}", ["event.event"]),
            (
                "a_computed_key_reads_a_global",
                "{inputs[event.properties.k]}",
                None,
                "{inputs[event.properties.k]}",
                ["inputs[event.properties.k]"],
            ),
            (
                "a_string_in_a_liquid_tag_is_text",
                "{{ 'event.properties.a' }} {{ event.properties.b }}",
                "liquid",
                "{{ 'event.properties.a' }} {{ event.properties.source.b }}",
                ["event.properties.a"],
            ),
            (
                "a_person_has_no_value",
                "{person.properties.email}",
                None,
                "{person.properties.email}",
                ["person.properties.email"],
            ),
            ("source_points_at_the_workflow", "{source.url}", None, "{source.url}", ["source.url"]),
        ]
    )
    def test_placeholders(
        self, _name: str, text: str, templating: str | None, expected: str, unknown: list[str]
    ) -> None:
        log = PlaceholderLog()

        assert rewrite_template(text, templating, log) == expected
        assert log.unknown == unknown
