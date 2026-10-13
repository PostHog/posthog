from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from products.alerts.backend.facade.contracts import DestinationHoldBack
from products.alerts.backend.facade.destinations import classify_alert_destinations
from products.alerts.backend.logic.destination_configs import SPEC_BY_TEMPLATE_ID
from products.alerts.backend.logic.destination_eligibility import _ADDRESS_INPUT_KEYS
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hog_functions.hog_function_revision import HogFunctionRevision

ALERT_ID = "01936a2e-0000-7000-8000-0000000000aa"
EVENT = "$logs_alert_firing"
WEBHOOK_INPUTS: dict[str, Any] = {
    "url": {"value": "https://hooks.example.com/hook"},
    "method": {"value": "POST"},
    "body": {"value": {"type": "logs_alert.firing"}},
    "headers": {"value": {"Content-Type": "application/json"}},
}
SLACK_INPUTS: dict[str, Any] = {
    "slack_workspace": {"value": 1},
    "channel": {"value": "C-1"},
    "text": {"value": "Log alert is firing"},
}


def test_every_native_template_names_where_it_sends() -> None:
    assert set(_ADDRESS_INPUT_KEYS) == set(SPEC_BY_TEMPLATE_ID)


def _with(inputs: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    return {**inputs, key: {"value": value}}


class TestDestinationEligibility(APIBaseTest):
    def _function(
        self, template_id: str, inputs: dict[str, Any], secret_keys: frozenset[str] = frozenset(), **fields: Any
    ) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name="Alert destination",
            type="internal_destination",
            template_id=template_id,
            enabled=True,
            inputs=inputs,
            inputs_schema=[{"key": key, "type": "string", "secret": key in secret_keys} for key in inputs],
            hog="return event",
            filters={
                "source": "internal-events",
                "events": [{"id": EVENT, "type": "events"}],
                "properties": [{"key": "alert_id", "value": ALERT_ID, "operator": "exact", "type": "event"}],
            },
            **fields,
        )

    def _classify(self) -> tuple[DestinationHoldBack, ...]:
        (eligibility,) = classify_alert_destinations(team_id=self.team.id, alert_id=ALERT_ID, allowed_event_ids=[EVENT])
        return eligibility.hold_backs

    def _edited(self, function: HogFunction, **changes: Any) -> None:
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

    @parameterized.expand(
        [
            ("a_moved_channel_is_still_native", "template-slack", SLACK_INPUTS, "channel", "C-2", ()),
            (
                "rewritten_slack_text",
                "template-slack",
                SLACK_INPUTS,
                "text",
                "<!here> it broke",
                (DestinationHoldBack.MESSAGE,),
            ),
            (
                "rewritten_webhook_body",
                "template-webhook",
                WEBHOOK_INPUTS,
                "body",
                {"text": "relay"},
                (DestinationHoldBack.WEBHOOK_BODY,),
            ),
            (
                "an_added_plain_auth_header_is_still_native",
                "template-webhook",
                WEBHOOK_INPUTS,
                "headers",
                {"Content-Type": "application/json", "Authorization": "Bearer not-a-real-token"},
                (),
            ),
            (
                "an_added_templated_header",
                "template-webhook",
                WEBHOOK_INPUTS,
                "headers",
                {"Authorization": "Bearer {inputs.token}"},
                (DestinationHoldBack.WEBHOOK_TEMPLATED_HEADER,),
            ),
        ]
    )
    def test_an_input_edit_holds_back_only_what_native_delivery_drops(
        self,
        _name: str,
        template_id: str,
        inputs: dict[str, Any],
        key: str,
        value: Any,
        expected: tuple[DestinationHoldBack, ...],
    ) -> None:
        function = self._function(template_id, inputs)
        self._edited(function, inputs=_with(inputs, key, value))

        assert self._classify() == expected

    @parameterized.expand(
        [
            ("edited_code", {"hog": "fetch(inputs.url, {'body': 'mine'})"}, (DestinationHoldBack.CODE,)),
            (
                "masking",
                {"masking": {"ttl": 3600, "hash": "{event.properties.alert_id}"}},
                (DestinationHoldBack.MASKING,),
            ),
        ]
    )
    def test_a_function_edit_holds_it_back(
        self, _name: str, changes: dict[str, Any], expected: tuple[DestinationHoldBack, ...]
    ) -> None:
        self._edited(self._function("template-webhook", WEBHOOK_INPUTS), **changes)

        assert self._classify() == expected

    @parameterized.expand(
        [
            ("built_before_tracking_and_saved_again", datetime(2026, 7, 1, tzinfo=UTC), timedelta(days=3), True),
            (
                "built_before_tracking_and_never_saved_again",
                datetime(2026, 7, 1, tzinfo=UTC),
                timedelta(seconds=1),
                False,
            ),
            ("built_after_tracking_without_an_edit", datetime(2026, 9, 1, tzinfo=UTC), timedelta(days=3), False),
        ]
    )
    def test_an_edit_from_before_edits_were_recorded_holds_it_back(
        self, _name: str, created_at: datetime, saved_after: timedelta, held_back: bool
    ) -> None:
        function = self._function("template-webhook", WEBHOOK_INPUTS)
        HogFunction.objects.filter(pk=function.pk).update(created_at=created_at, updated_at=created_at + saved_after)

        assert self._classify() == ((DestinationHoldBack.UNTRACKED_EDIT,) if held_back else ())

    def test_a_signed_webhook_is_held_back(self) -> None:
        self._function(
            "template-webhook",
            {**WEBHOOK_INPUTS, "signing_secret": {"value": "whsec_not-a-real-secret"}},
            secret_keys=frozenset({"signing_secret"}),
        )

        assert self._classify() == (DestinationHoldBack.WEBHOOK_SIGNING,)

    def test_a_template_native_delivery_does_not_know_is_held_back(self) -> None:
        self._function("template-some-custom-sink", {"url": {"value": "https://hooks.example.com/hook"}})

        assert self._classify() == (DestinationHoldBack.UNRECOGNIZED_TEMPLATE,)
