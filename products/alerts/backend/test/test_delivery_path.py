from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts.backend.facade.contracts import DeliveryPathChoice, DestinationEligibility, HogFunctionPathReason
from products.alerts.backend.logic.delivery_path import _TeamDestinations
from products.alerts_platform.backend.facade.contracts import DeliveryPath, SourceKind


def _destination(template_id: str, event_id: str) -> DestinationEligibility:
    return DestinationEligibility(
        hog_function_id=uuid4(),
        template_id=template_id,
        hold_backs=(),
        code_hash="",
        event_ids=frozenset({event_id}),
    )


class TestDeliveryPathChoice(SimpleTestCase):
    @parameterized.expand(
        [
            (
                SourceKind.INSIGHT,
                "$insight_alert_firing",
                DeliveryPathChoice(reason=HogFunctionPathReason.PAGERDUTY_NOT_NATIVE),
            ),
            (SourceKind.INSIGHT, "$insight_alert_incident_opened", DeliveryPathChoice()),
            (SourceKind.LOGS, "$logs_alert_incident_opened", DeliveryPathChoice()),
        ]
    )
    def test_a_stock_pagerduty_destination_keeps_its_hog_function_only_on_the_insight_firing_event(
        self, source: SourceKind, event_id: str, expected: DeliveryPathChoice
    ) -> None:
        team = _TeamDestinations(source=source, team_id=1, allowed_event_ids=())

        paged = team.choice([_destination("template-pagerduty", event_id), _destination("template-slack", event_id)])
        # Another alert of the same team, so the choice is per alert.
        other = team.choice([_destination("template-slack", event_id)])

        assert (paged, other.path) == (expected, DeliveryPath.NATIVE)

    @parameterized.expand(
        [
            ("logs_keeps_legacy_body", SourceKind.LOGS, True, DeliveryPathChoice()),
            ("logs_gets_platform_body", SourceKind.LOGS, False, DeliveryPathChoice()),
            (
                "insight_keeps_legacy_body",
                SourceKind.INSIGHT,
                True,
                DeliveryPathChoice(reason=HogFunctionPathReason.LEGACY_WEBHOOK_BODY_NOT_NATIVE),
            ),
            ("insight_gets_platform_body", SourceKind.INSIGHT, False, DeliveryPathChoice()),
            (
                "unreadable_flag",
                SourceKind.LOGS,
                None,
                DeliveryPathChoice(reason=HogFunctionPathReason.WEBHOOK_BODY_UNKNOWN),
            ),
        ]
    )
    def test_a_stock_webhook_delivers_natively_unless_its_team_keeps_a_body_native_delivery_lacks(
        self, _name: str, source: SourceKind, keeps_legacy_body: bool | None, expected: DeliveryPathChoice
    ) -> None:
        team = _TeamDestinations(source=source, team_id=1, allowed_event_ids=())
        event_id = f"${source.value}_alert_firing"

        with (
            patch("products.alerts.backend.logic.delivery_path.Team.objects.get"),
            patch(
                "products.alerts.backend.logic.delivery_path.keeps_legacy_webhook_body", return_value=keeps_legacy_body
            ),
        ):
            assert team.choice([_destination("template-webhook", event_id)]) == expected
