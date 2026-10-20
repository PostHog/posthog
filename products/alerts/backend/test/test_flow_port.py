import base64
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts.backend.facade.contracts import FlowPort, FlowPortProblem
from products.alerts.backend.facade.destinations import flow_ports
from products.alerts.backend.logic.flow_port import PlaceholderLog, rewrite_template
from products.alerts_platform.backend.facade.contracts import AlertEventKind
from products.alerts_platform.backend.facade.testing import create_configuration
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hog_functions.hog_function_revision import HogFunctionRevision

ALERT_ID = "01936a2e-0000-7000-8000-0000000000aa"
TRANSITIONS = {
    "$logs_alert_firing": AlertEventKind.FIRING,
    "$logs_alert_resolved": AlertEventKind.RESOLVED,
    "$logs_alert_errored": AlertEventKind.ERRORED,
    "$logs_alert_auto_disabled": AlertEventKind.BROKEN,
}
EVENT_IDS = [*TRANSITIONS, "$logs_alert_incident_opened"]
SIGNING_SECRET = "whsec_" + base64.b64encode(b"not-a-real-secret-but-24-bytes").decode()
STOCK_BODY = {"type": "logs_alert.firing"}
WEBHOOK_INPUTS: dict[str, Any] = {
    "url": {"value": "https://hooks.example.com/hook"},
    "method": {"value": "POST"},
    "body": {"value": STOCK_BODY},
}


class TestFlowPorts(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        with team_scope(self.team.id):
            self.configuration = create_configuration(
                team=self.team,
                name="API errors",
                source_kind="logs",
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
            filters={
                "source": "internal-events",
                "events": [{"id": event, "type": "events"}],
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
                alerts=[(alert_id, "API errors")],
                allowed_event_ids=EVENT_IDS,
                transition_by_event_id=TRANSITIONS,
            )
        )

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

        HogFunction.objects.filter(team=self.team, template_id="template-webhook").update(
            masking={"ttl": 3600, "hash": "{event.properties.alert_id}", "threshold": None}
        )

        (port,) = self._ports()

        assert port.issues == ()
        assert port.left_out == (disabled_errored_twin.id,)
        assert port.rewrites == (
            "event.properties.alert_name -> event.properties.source.alert_name",
            "event.properties.result_count -> event.properties.source.result_count",
            "event.properties.alert_id -> event.properties.source.alert_id",
        )
        assert port.flow is not None
        flow = port.flow
        assert flow["status"] == "draft"
        assert flow["trigger_masking"] == {
            "ttl": 3600,
            "hash": "{event.properties.transition}:{event.properties.source.alert_id}",
            "threshold": None,
        }
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
            ("edited_code", {"hog": "fetch(inputs.url)"}, FlowPortProblem.EDITED_CODE),
        ]
    )
    def test_a_destination_a_flow_cannot_carry_is_reported_without_a_flow(
        self, _name: str, setup: dict[str, Any], problem: FlowPortProblem
    ) -> None:
        hog = setup.pop("hog", None)
        function = self._function(**{"secret": SIGNING_SECRET, **setup})
        self._edit(
            function, **({"hog": hog} if hog else {"inputs": {**(function.inputs or {}), "method": {"value": "PUT"}}})
        )

        (port,) = self._ports()

        assert port.flow is None
        assert problem in {issue.problem for issue in port.issues}

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
