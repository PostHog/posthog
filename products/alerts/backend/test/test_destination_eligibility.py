import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts.backend.facade.contracts import (
    INSIGHT_ALERT_EVENT_IDS,
    DestinationBucket,
    DestinationEligibility,
    DestinationHoldBack,
)
from products.alerts.backend.facade.destinations import (
    bucket_for,
    classify_alert_destinations,
    unbound_alert_destinations,
)
from products.alerts.backend.logic.destination_bucket_report import bucketed_destinations
from products.alerts.backend.logic.destination_eligibility import LOGS_STOCK_INPUT_VALUES, STOCK_INPUT_VALUES
from products.alerts.backend.logic.insight_alert_destinations import build_insight_alert_slack_config
from products.alerts_platform.backend.facade.contracts import AlertDestinationData, DestinationType
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hog_functions.hog_function_revision import HogFunctionRevision

ALERT_ID = "01936a2e-0000-7000-8000-0000000000aa"
EVENT = "$logs_alert_firing"
WEBHOOK_INPUTS: dict[str, Any] = {
    "url": {"value": "https://hooks.example.com/hook"},
    "method": {"value": "POST"},
    "body": {"value": LOGS_STOCK_INPUT_VALUES["template-webhook"]["body"][0]},
    "headers": {"value": {"Content-Type": "application/json"}},
}
PAGERDUTY_INPUTS: dict[str, Any] = {
    "routing_key": {"value": "not-a-real-key"},
    "severity": {"value": "critical"},
    "region": {"value": "us"},
}
INSIGHT_SLACK_DATA: AlertDestinationData = {
    "type": DestinationType.SLACK,
    "slack_workspace_id": 1,
    "slack_channel_id": "C-1",
}
SLACK_INPUTS: dict[str, Any] = {
    "slack_workspace": {"value": 1},
    "channel": {"value": "C-1"},
    "text": {"value": LOGS_STOCK_INPUT_VALUES["template-slack"]["text"][0]},
}


def _with(inputs: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    return {**inputs, key: {"value": value}}


class TestDestinationEligibility(APIBaseTest):
    def _function(
        self,
        template_id: str,
        inputs: dict[str, Any],
        secret_keys: frozenset[str] = frozenset(),
        alert_id: str | None = ALERT_ID,
        enabled: bool = True,
        **fields: Any,
    ) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name="Alert destination",
            type="internal_destination",
            template_id=template_id,
            enabled=enabled,
            inputs=inputs,
            inputs_schema=[{"key": key, "type": "string", "secret": key in secret_keys} for key in inputs],
            hog="return event",
            filters={
                "source": "internal-events",
                "events": [{"id": EVENT, "type": "events"}],
                "properties": [{"key": "alert_id", "value": alert_id, "operator": "exact", "type": "event"}]
                if alert_id
                else [],
            },
            **fields,
        )

    def _eligibility(self) -> DestinationEligibility:
        (eligibility,) = classify_alert_destinations(team_id=self.team.id, alert_id=ALERT_ID, allowed_event_ids=[EVENT])
        return eligibility

    def _classify(self) -> tuple[DestinationHoldBack, ...]:
        return self._eligibility().hold_backs

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
                "an_added_header_native_delivery_cannot_send",
                "template-webhook",
                WEBHOOK_INPUTS,
                "headers",
                {"Content-Type": "application/json", "X Bad": "ok"},
                (DestinationHoldBack.WEBHOOK_HEADERS,),
            ),
            (
                "slack_bot_emoji",
                "template-slack",
                SLACK_INPUTS,
                "icon_emoji",
                ":rotating_light:",
                (DestinationHoldBack.MESSAGE_COSMETIC,),
            ),
            ("slack_text_saved_with_the_default_mode", "template-slack", SLACK_INPUTS, "text", "hog", ()),
            (
                "slack_text_moved_to_liquid",
                "template-slack",
                SLACK_INPUTS,
                "text",
                None,
                (DestinationHoldBack.MESSAGE,),
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
        if value is None:
            edited = {**inputs, key: {**inputs[key], "templating": "liquid"}}
        elif value == "hog":
            edited = {**inputs, key: {**inputs[key], "templating": "hog"}}
        else:
            edited = _with(inputs, key, value)
        self._edited(function, inputs=edited)

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

        eligibility = self._eligibility()
        assert eligibility.hold_backs == expected
        # The code-family registry is keyed by the md5 of the code as it runs now.
        current_hog = changes.get("hog", "return event")
        assert eligibility.code_hash == hashlib.md5(current_hog.encode(), usedforsecurity=False).hexdigest()

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

    @parameterized.expand(
        [
            ("webhook_url", "template-webhook", WEBHOOK_INPUTS, "url", frozenset()),
            (
                "secret_pagerduty_routing_key",
                "template-pagerduty",
                {"routing_key": {"value": "key"}, "severity": {"value": "critical"}},
                "routing_key",
                frozenset({"routing_key"}),
            ),
        ]
    )
    def test_a_templated_address_is_held_back(
        self, _name: str, template_id: str, inputs: dict[str, Any], key: str, secret_keys: frozenset[str]
    ) -> None:
        self._function(template_id, _with(inputs, key, "{event.properties.alert_id}"), secret_keys=secret_keys)

        assert self._classify() == (DestinationHoldBack.TEMPLATED_ADDRESS,)

    def test_a_revision_taken_long_after_an_untracked_build_is_no_baseline(self) -> None:
        function = self._function("template-slack", SLACK_INPUTS)
        HogFunction.objects.filter(pk=function.pk).update(created_at=datetime(2026, 7, 1, tzinfo=UTC))
        function.refresh_from_db()
        self._edited(function, inputs=_with(SLACK_INPUTS, "channel", "C-2"))

        assert self._classify() == (DestinationHoldBack.UNTRACKED_EDIT,)

    @parameterized.expand(
        [
            ("plain_http", "template-webhook", _with(WEBHOOK_INPUTS, "url", "http://hooks.example.com/hook")),
            ("malformed", "template-webhook", _with(WEBHOOK_INPUTS, "url", "https://[invalid/hook")),
            ("unknown_severity", "template-pagerduty", {**PAGERDUTY_INPUTS, "severity": {"value": "urgent"}}),
            ("unknown_region", "template-pagerduty", {**PAGERDUTY_INPUTS, "region": {"value": "apac"}}),
        ]
    )
    def test_a_destination_native_delivery_refuses_is_held_back(
        self, _name: str, template_id: str, inputs: dict[str, Any]
    ) -> None:
        self._function(template_id, inputs)

        assert self._classify() == (DestinationHoldBack.REFUSED_ADDRESS,)

    def test_a_signed_webhook_is_held_back(self) -> None:
        self._function(
            "template-webhook",
            {**WEBHOOK_INPUTS, "signing_secret": {"value": "whsec_not-a-real-secret"}},
            secret_keys=frozenset({"signing_secret"}),
        )

        assert self._classify() == (DestinationHoldBack.WEBHOOK_SIGNING,)

    @parameterized.expand(
        [
            ("other_template", "template-some-custom-sink", None, (DestinationHoldBack.OTHER_TEMPLATE,)),
            (
                "other_template_with_edited_code",
                "template-some-custom-sink",
                "fetch('https://hooks.example.com/hook')",
                (DestinationHoldBack.OTHER_TEMPLATE, DestinationHoldBack.CODE),
            ),
            ("no_template", "", None, (DestinationHoldBack.NO_TEMPLATE,)),
        ]
    )
    def test_a_template_native_delivery_does_not_know_is_held_back(
        self, _name: str, template_id: str, edited_hog: str | None, expected: tuple[DestinationHoldBack, ...]
    ) -> None:
        function = self._function(template_id, {"url": {"value": "https://hooks.example.com/hook"}})
        if edited_hog is not None:
            self._edited(function, hog=edited_hog)
        reads_captured_events = self._function(template_id, {})
        HogFunction.objects.filter(pk=reads_captured_events.pk).update(type="destination")

        assert self._classify() == expected

    def test_a_function_no_alert_owns_is_unbound(self) -> None:
        self._function("template-slack", SLACK_INPUTS)
        team_wide = self._function("template-slack", SLACK_INPUTS, alert_id=None)
        self._function("template-slack", SLACK_INPUTS, alert_id=None, enabled=False)
        untyped_event = self._function("template-slack", SLACK_INPUTS, alert_id=None)
        HogFunction.objects.filter(pk=untyped_event.pk).update(
            filters={**(untyped_event.filters or {}), "events": [{"id": EVENT}]}
        )
        captured_events = self._function("template-slack", SLACK_INPUTS, alert_id=None)
        HogFunction.objects.filter(pk=captured_events.pk).update(type="destination")
        self._function("template-slack", SLACK_INPUTS, alert_id="01936a2e-0000-7000-8000-0000000000dd")
        excluding_one_alert = self._function("template-slack", SLACK_INPUTS)
        HogFunction.objects.filter(pk=excluding_one_alert.pk).update(
            filters={
                **(excluding_one_alert.filters or {}),
                "properties": [{"key": "alert_id", "value": ALERT_ID, "operator": "is_not", "type": "event"}],
            }
        )

        assert unbound_alert_destinations(team_id=self.team.id, allowed_event_ids=[EVENT]) == (
            team_wide.id,
            untyped_event.id,
            excluding_one_alert.id,
        )

    def test_the_report_buckets_an_unbound_function_by_its_content_once_per_team(self) -> None:
        other_alert = "01936a2e-0000-7000-8000-0000000000dd"
        bound = self._function("template-slack", SLACK_INPUTS)
        self._function("template-slack", SLACK_INPUTS, alert_id=other_alert)
        team_wide = self._function("template-slack", SLACK_INPUTS, alert_id=None)
        self._edited(team_wide, hog="fetch('https://hooks.example.com/hook')")
        excluding_one_alert = self._function("template-slack", SLACK_INPUTS)
        HogFunction.objects.filter(pk=excluding_one_alert.pk).update(
            filters={
                **(excluding_one_alert.filters or {}),
                "properties": [{"key": "alert_id", "value": ALERT_ID, "operator": "is_not", "type": "event"}],
            }
        )

        report = list(
            bucketed_destinations([(self.team.id, ALERT_ID), (self.team.id, other_alert)], allowed_event_ids=[EVENT])
        )

        assert [(d.alert_id, d.eligibility.hog_function_id, bucket_for(d.eligibility)) for d in report[:3]] == [
            (None, team_wide.id, DestinationBucket.CODE),
            (None, excluding_one_alert.id, DestinationBucket.STOCK),
            (ALERT_ID, bound.id, DestinationBucket.STOCK),
        ]
        assert [d.alert_id for d in report] == [None, None, ALERT_ID, other_alert]

    @parameterized.expand(
        [
            ("stock_message", {}, None, ()),
            ("custom_attachments", {"attachments": [{"text": "Custom message"}]}, None, (DestinationHoldBack.MESSAGE,)),
            (
                "legacy_stock_blocks",
                {"blocks": STOCK_INPUT_VALUES["template-slack"]["blocks"][0]},
                None,
                (),
            ),
            ("text_edited_before_the_first_save", {"text": "Look at this"}, {}, (DestinationHoldBack.MESSAGE,)),
            ("text_edited_with_no_revision", {"text": "Look at this"}, None, (DestinationHoldBack.MESSAGE,)),
            ("an_emptied_text", {"text": ""}, None, ()),
            (
                "stock_text_rendered_as_liquid",
                {"text": {"value": "Alert triggered: {event.properties.insight_name}", "templating": "liquid"}},
                None,
                (DestinationHoldBack.MESSAGE,),
            ),
            (
                "an_agent_chosen_emoji",
                {"icon_emoji": ":rotating_light:"},
                {},
                (DestinationHoldBack.MESSAGE_COSMETIC,),
            ),
            (
                "text_moved_to_another_default_after_the_first_save",
                {"text": "*{person.name}* triggered event: '{event.event}'"},
                {"text": "Alert triggered: {event.properties.insight_name}"},
                (),
            ),
            (
                "text_edited_after_the_first_save",
                {},
                {"text": "Look at this"},
                (DestinationHoldBack.MESSAGE,),
            ),
        ]
    )
    def test_an_insight_destination_is_compared_with_the_shipped_defaults(
        self,
        _name: str,
        changes: dict[str, Any],
        later: dict[str, str] | None,
        expected: tuple[DestinationHoldBack, ...],
    ) -> None:
        (event,) = INSIGHT_ALERT_EVENT_IDS
        stock = build_insight_alert_slack_config(
            alert_id=ALERT_ID,
            alert_name="API errors",
            data=INSIGHT_SLACK_DATA,
        ).payload
        function = self._function(
            "template-slack",
            {
                **stock["inputs"],
                **{key: value if isinstance(value, dict) else {"value": value} for key, value in changes.items()},
            },
        )
        HogFunction.objects.filter(pk=function.pk).update(filters=stock["filters"])
        if later is not None:
            function.refresh_from_db()
            self._edited(
                function, inputs={**(function.inputs or {}), **{key: {"value": value} for key, value in later.items()}}
            )

        (eligibility,) = classify_alert_destinations(team_id=self.team.id, alert_id=ALERT_ID, allowed_event_ids=[event])
        assert eligibility.hold_backs == expected

    @parameterized.expand(
        [
            ("logs_default", LOGS_STOCK_INPUT_VALUES["template-slack"]["text"][1], ()),
            ("own_text", "Look at this", (DestinationHoldBack.MESSAGE,)),
            ("insight_default", STOCK_INPUT_VALUES["template-slack"]["text"][0], (DestinationHoldBack.MESSAGE,)),
        ]
    )
    def test_a_logs_destination_built_without_a_revision_is_compared_with_logs_defaults(
        self, _name: str, text: str, expected: tuple[DestinationHoldBack, ...]
    ) -> None:
        self._function("template-slack", _with(SLACK_INPUTS, "text", text))

        assert self._classify() == expected


class TestBucketFor(SimpleTestCase):
    @parameterized.expand(
        [
            ("stock", (), DestinationBucket.STOCK),
            ("other_template", (DestinationHoldBack.OTHER_TEMPLATE,), DestinationBucket.PORTABLE),
            ("no_template", (DestinationHoldBack.NO_TEMPLATE,), DestinationBucket.CODE),
            (
                "refused_address_over_code",
                (DestinationHoldBack.CODE, DestinationHoldBack.REFUSED_ADDRESS),
                DestinationBucket.REFUSED_ADDRESS,
            ),
            ("code_over_message", (DestinationHoldBack.MESSAGE, DestinationHoldBack.CODE), DestinationBucket.CODE),
            (
                "message_over_cosmetic",
                (DestinationHoldBack.MESSAGE_COSMETIC, DestinationHoldBack.MESSAGE),
                DestinationBucket.PORTABLE,
            ),
            ("cosmetic", (DestinationHoldBack.MESSAGE_COSMETIC,), DestinationBucket.COSMETIC),
            (
                "templated_over_static_headers",
                (DestinationHoldBack.WEBHOOK_HEADERS, DestinationHoldBack.WEBHOOK_TEMPLATED_HEADER),
                DestinationBucket.TEMPLATED_HEADERS,
            ),
            ("static_headers", (DestinationHoldBack.WEBHOOK_HEADERS,), DestinationBucket.STATIC_HEADERS),
        ]
    )
    def test_the_most_restrictive_hold_back_decides(
        self, _name: str, hold_backs: tuple[DestinationHoldBack, ...], expected: DestinationBucket
    ) -> None:
        eligibility = DestinationEligibility(
            hog_function_id=UUID(int=1), template_id="template-webhook", hold_backs=hold_backs, code_hash=""
        )

        assert bucket_for(eligibility) == expected
