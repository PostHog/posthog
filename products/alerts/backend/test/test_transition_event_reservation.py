from django.test import SimpleTestCase

from products.alerts_platform.backend.facade.contracts import ALERT_TRANSITION_EVENT
from products.cdp.backend.internal_events import is_reserved_internal_event


class TestTransitionEventReservation(SimpleTestCase):
    def test_the_event_the_platform_emits_is_closed_to_user_created_destinations(self) -> None:
        assert is_reserved_internal_event(ALERT_TRANSITION_EVENT)
