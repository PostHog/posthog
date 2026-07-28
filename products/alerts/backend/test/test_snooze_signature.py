from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.tasks.alerts.utils import trigger_alert_hog_functions

from products.alerts.backend.facade.api import sign_insight_alert_id, verify_insight_alert_id
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight


class TestInsightAlertSignature(SimpleTestCase):
    def test_signature_round_trips(self):
        alert_id = "019f957b-e747-0000-b0ab-f9010be3d0c7"
        assert verify_insight_alert_id(alert_id, sign_insight_alert_id(alert_id))

    def test_signature_rejects_a_different_id(self):
        # The whole point: a signature made for one alert must not validate another id.
        sig = sign_insight_alert_id("019f957b-e747-0000-b0ab-f9010be3d0c7")
        assert not verify_insight_alert_id("aaaaaaaa-0000-0000-0000-000000000000", sig)

    def test_signature_rejects_tampering(self):
        alert_id = "019f957b-e747-0000-b0ab-f9010be3d0c7"
        assert not verify_insight_alert_id(alert_id, sign_insight_alert_id(alert_id)[:-1] + "0")


class TestAlertFiringEmitsSignature(APIBaseTest):
    @patch("posthog.tasks.alerts.utils.produce_internal_event")
    def test_firing_event_carries_a_verifying_signature(self, mock_produce):
        insight = Insight.objects.create(team=self.team, short_id="sigtest", name="Signups")
        alert = AlertConfiguration.objects.create(team=self.team, insight=insight, name="Signups alert")

        trigger_alert_hog_functions(alert, {"breaches": "x"})

        props = mock_produce.call_args.kwargs["event"].properties
        assert verify_insight_alert_id(props["alert_id"], props["alert_id_sig"])
