from uuid import uuid4

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
