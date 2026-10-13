import hmac
import json
import hashlib

from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.test import override_settings

from requests import RequestException

from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.models.organization_integration import OrganizationIntegration

from ee.api.vercel.test.base import VercelTestBase

SECRET = "test_webhook_secret"


def _forward_response(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    return response


@override_settings(VERCEL_CLIENT_INTEGRATION_SECRET=SECRET)
class TestVercelWebhooks(VercelTestBase):
    def setUp(self):
        super().setUp()
        self.url = "/webhooks/vercel"
        reset_consumer_registry()
        self.addCleanup(reset_consumer_registry)

        self.addCleanup(patch.stopall)
        # `pytest.ini` sets DEBUG, which makes `posthog/regions.py` rewrite both domains to
        # localhost hosts where neither branch of the forward is reachable. `testserver` is the
        # secondary region here, because that is the region Vercel's one webhook URL names.
        patch("posthog.regions.SECONDARY_REGION_DOMAIN", "testserver").start()
        patch("posthog.regions.PRIMARY_REGION_DOMAIN", "eu.posthog.com").start()

        self.forward = patch("posthog.ingress.dispatch.forward.requests.request").start()
        self.forward.return_value = _forward_response(202)

    def _post(self, payload: dict, signature: str | None = "sign"):
        body = json.dumps(payload).encode("utf-8")
        if signature == "sign":
            signature = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha1).hexdigest()
        headers = {"x-vercel-signature": signature} if signature is not None else {}
        return self.client.post(self.url, data=body, content_type="application/json", headers=headers, secure=True)

    def _billing_payload(self, installation_id: str) -> dict:
        return {
            "type": "marketplace.invoice.paid",
            "payload": {"installationId": installation_id, "invoiceId": "mi_123"},
        }

    def _deauthorization_payload(self, installation_id: str) -> dict:
        return {"type": "integration-configuration.removed", "payload": {"installationId": installation_id}}

    def test_an_invalid_signature_is_refused(self):
        response = self._post(self._billing_payload(self.installation_id), signature="invalid_signature")

        self.assertEqual(response.status_code, 401)
        self.forward.assert_not_called()

    def test_a_missing_signature_is_refused(self):
        response = self._post(self._billing_payload(self.installation_id), signature=None)

        self.assertEqual(response.status_code, 401)

    @override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="")
    @patch("posthog.ingress.views.capture_exception")
    def test_a_missing_secret_is_refused_and_reported(self, capture):
        # The 401 is the same one a stranger's bad signature gets, so a dropped secret is
        # invisible in the status codes while every invoice event is refused.
        response = self._post(self._billing_payload(self.installation_id))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(capture.call_count, 1)

    @patch("ee.api.vercel.webhook_events.BillingManager")
    def test_a_billing_event_without_an_installation_id_runs_no_billing_call(self, billing_manager):
        response = self._post({"type": "marketplace.invoice.paid", "payload": {"invoiceId": "mi_123"}})

        self.assertEqual(response.status_code, 202)
        billing_manager.assert_not_called()
        self.forward.assert_not_called()

    @patch("ee.api.vercel.webhook_events.VercelIntegration")
    def test_a_deauthorization_without_a_configuration_id_deletes_nothing(self, vercel_integration):
        response = self._post({"type": "integration-configuration.removed", "payload": {"user": {"id": "usr_123"}}})

        self.assertEqual(response.status_code, 202)
        vercel_integration.delete_installation.assert_not_called()
        self.forward.assert_not_called()

    @patch("ee.api.vercel.webhook_events.VercelIntegration")
    def test_a_deauthorization_this_region_holds_deletes_the_installation(self, vercel_integration):
        response = self._post(self._deauthorization_payload(self.installation_id))

        self.assertEqual(response.status_code, 202)
        vercel_integration.delete_installation.assert_called_once_with(self.installation_id)
        self.forward.assert_not_called()

    def test_a_connectable_deauthorization_deletes_the_row_directly(self):
        self.installation.config["type"] = "connectable"
        self.installation.save()

        response = self._post(self._deauthorization_payload(self.installation_id))

        self.assertEqual(response.status_code, 202)
        self.assertFalse(OrganizationIntegration.objects.filter(integration_id=self.installation_id).exists())

    def test_a_deauthorization_can_name_the_installation_under_configuration_id(self):
        self.installation.config["type"] = "connectable"
        self.installation.save()

        response = self._post(
            {
                "type": "integration-configuration.removed",
                "payload": {"configuration": {"id": self.installation_id}},
            }
        )

        self.assertEqual(response.status_code, 202)
        self.assertFalse(OrganizationIntegration.objects.filter(integration_id=self.installation_id).exists())

    @patch("ee.api.vercel.webhook_events.BillingManager")
    def test_an_event_type_this_integration_does_not_act_on_runs_nothing(self, billing_manager):
        for event_type in ["deployment.created", "marketplace.member.created", None]:
            with self.subTest(event_type=event_type):
                response = self._post({"type": event_type, "payload": {"installationId": self.installation_id}})

                self.assertEqual(response.status_code, 202)

        billing_manager.assert_not_called()
        self.forward.assert_not_called()

    @patch("ee.api.vercel.webhook_events.BillingManager")
    @patch("ee.api.vercel.webhook_events.License")
    def test_a_billing_event_this_region_holds_reaches_the_billing_service(self, license_model, billing_manager_class):
        license_model.objects.first.return_value = MagicMock()
        billing_manager = MagicMock()
        billing_manager_class.return_value = billing_manager
        payload = self._billing_payload(self.installation_id)

        response = self._post(payload)

        self.assertEqual(response.status_code, 202)
        billing_manager.handle_billing_provider_webhook.assert_called_once_with(
            event_type="marketplace.invoice.paid",
            event_data=payload["payload"],
            organization=self.organization,
            billing_provider="vercel",
        )
        self.forward.assert_not_called()

    @patch("ee.api.vercel.webhook_events.BillingManager")
    def test_a_billing_event_the_other_region_holds_is_forwarded_and_not_billed_here(self, billing_manager):
        response = self._post(self._billing_payload("icfg_unknown"))

        self.assertEqual(response.status_code, 202)
        billing_manager.assert_not_called()
        self.forward.assert_called_once()
        self.assertEqual(self.forward.call_args.kwargs["url"], "https://eu.posthog.com/webhooks/vercel")
        # The other region waits up to 30 s for the billing service, so a shorter deadline here
        # would abandon an invoice it is still processing.
        self.assertGreater(self.forward.call_args.kwargs["timeout"], 30)

    def test_the_forwarded_request_carries_the_signature_the_other_region_checks(self):
        self._post(self._billing_payload("icfg_unknown"))

        headers = {key.lower(): value for key, value in self.forward.call_args.kwargs["headers"].items()}
        self.assertIn("x-vercel-signature", headers)
        # The other region reads which region it is off the connection, so a forwarded host would
        # make it forward the delivery on again.
        self.assertNotIn("host", headers)

    def test_a_forward_that_fails_is_not_receipted(self):
        self.forward.side_effect = RequestException("boom")

        response = self._post(self._billing_payload("icfg_unknown"))

        self.assertEqual(response.status_code, 500)

    def test_a_forward_the_other_region_refuses_is_not_receipted(self):
        self.forward.return_value = _forward_response(500)

        response = self._post(self._billing_payload("icfg_unknown"))

        self.assertEqual(response.status_code, 500)

    @patch("ee.api.vercel.webhook_events.BillingManager")
    @patch("ee.api.vercel.webhook_events._get_integration", side_effect=OperationalError("statement timeout"))
    def test_an_ownership_lookup_that_fails_dispatches_nothing(self, _lookup, billing_manager):
        # A lookup that did not answer rules no region out. Dispatching anyway would run the
        # consumer, find nothing local, and receipt a delivery the owning region never sees.
        response = self._post(self._billing_payload(self.installation_id))

        self.assertEqual(response.status_code, 500)
        self.forward.assert_not_called()
        billing_manager.assert_not_called()

    @patch("ee.api.vercel.webhook_events.logger")
    def test_an_installation_no_region_holds_is_reported_quietly_in_the_region_that_forwards(self, logger):
        # This region sees a local miss for every event of every installation the other region
        # holds, so a warning here would fire on all of them.
        response = self._post(self._billing_payload("icfg_unknown"))

        self.assertEqual(response.status_code, 202)
        self.assertNotIn("vercel_webhook_unknown_config", [call.args[0] for call in logger.warning.call_args_list])
        self.assertIn("vercel_webhook_unknown_config", [call.args[0] for call in logger.info.call_args_list])

    @patch("ee.api.vercel.webhook_events.logger")
    def test_an_installation_no_region_holds_is_reported_by_the_region_that_looks_last(self, logger):
        # Both regions have looked by the time the forwarded request lands here, so this miss is
        # the one worth a warning, and the delivery is receipted rather than retried forever.
        with (
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver"),
            patch("posthog.regions.SECONDARY_REGION_DOMAIN", "us.posthog.com"),
        ):
            response = self._post(self._billing_payload("icfg_unknown"))

        self.assertEqual(response.status_code, 202)
        self.assertIn("vercel_webhook_unknown_config", [call.args[0] for call in logger.warning.call_args_list])

    def test_the_region_that_receives_forwards_never_forwards_again(self):
        # Without this guard a delivery no region holds would bounce between the two regions.
        with (
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver"),
            patch("posthog.regions.SECONDARY_REGION_DOMAIN", "us.posthog.com"),
        ):
            response = self._post(self._billing_payload("icfg_unknown"))

        self.assertEqual(response.status_code, 202)
        self.forward.assert_not_called()

    @patch("ee.api.vercel.webhook_events.BillingManager")
    @patch("ee.api.vercel.webhook_events.License")
    def test_a_billing_service_error_is_not_receipted(self, license_model, billing_manager_class):
        license_model.objects.first.return_value = MagicMock()
        billing_manager = MagicMock()
        billing_manager_class.return_value = billing_manager
        billing_manager.handle_billing_provider_webhook.side_effect = Exception("Billing service error")

        response = self._post(self._billing_payload(self.installation_id))

        self.assertEqual(response.status_code, 500)

    @patch("ee.api.vercel.webhook_events.License")
    def test_a_missing_license_is_not_receipted(self, license_model):
        license_model.objects.first.return_value = None

        response = self._post(self._billing_payload(self.installation_id))

        self.assertEqual(response.status_code, 500)
