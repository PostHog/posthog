from uuid import uuid4

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts.backend.facade.contracts import DeliveryPathChoice, DestinationEligibility, HogFunctionPathReason
from products.alerts.backend.logic.delivery_path import _TeamDestinations
from products.alerts_platform.backend.facade.contracts import DeliveryPath, SourceKind


def _destination(template_id: str) -> DestinationEligibility:
    return DestinationEligibility(hog_function_id=uuid4(), template_id=template_id, hold_backs=(), code_hash="")


class TestDeliveryPathChoice(SimpleTestCase):
    @parameterized.expand(
        [
            # Native insight delivery sends no incident actions, so the function keeps opening them.
            (SourceKind.INSIGHT, DeliveryPathChoice(reason=HogFunctionPathReason.PAGERDUTY_NOT_NATIVE)),
            (SourceKind.LOGS, DeliveryPathChoice()),
        ]
    )
    def test_a_stock_pagerduty_destination_keeps_its_hog_function_only_for_insight(
        self, source: SourceKind, expected: DeliveryPathChoice
    ) -> None:
        team = _TeamDestinations(source=source, team_id=1, allowed_event_ids=())

        paged = team.choice([_destination("template-pagerduty"), _destination("template-slack")])
        # Another alert of the same team, so the choice is per alert.
        other = team.choice([_destination("template-slack")])

        assert (paged, other.path) == (expected, DeliveryPath.NATIVE)
