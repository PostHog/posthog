import json

from posthog.models.oauth import OAuthApplication
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, StripeProvisioningTestBase


class TestUpdateService(StripeProvisioningTestBase):
    def _url(self, resource_id) -> str:
        return f"{BASE_PATH}/provisioning/resources/{resource_id}/update_service"

    def test_update_to_free_succeeds(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(self._url(self.team.id), data={"service_id": "free"}, token=token)
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "complete"
        assert body["service_id"] == "free"
        assert TeamProvisioningConfig.objects.get(team=self.team).service_id == "free"

    def test_bearer_alone_is_not_enough(self):
        # update_service changes billing, so the orchestrator HMAC is required
        # on top of the bearer token.
        token = self._get_bearer_token()
        res = self.client.post(
            self._url(self.team.id),
            data=json.dumps({"service_id": "free"}),
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert res.status_code == 401
        assert res.json() == {"error": {"code": "invalid_signature", "message": "Signature verification failed"}}

    def test_missing_and_unknown_service_ids_rejected(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(self._url(self.team.id), data={}, token=token)
        assert res.status_code == 400
        assert res.json() == {
            "status": "error",
            "id": str(self.team.id),
            "error": {"code": "missing_service_id", "message": "service_id is required"},
        }

        res = self._post_signed_with_bearer(self._url(self.team.id), data={"service_id": "bogus"}, token=token)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "unknown_service"

    def test_resource_owned_by_another_partner_is_forbidden(self):
        token = self._get_bearer_token()
        other_app = OAuthApplication.objects.create(
            client_id="other-partner",
            name="Other Partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://localhost",
            algorithm="RS256",
        )
        TeamProvisioningConfig.objects.update_or_create(team=self.team, defaults={"application": other_app})

        res = self._post_signed_with_bearer(self._url(self.team.id), data={"service_id": "free"}, token=token)
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "forbidden"
        assert res.json()["error"]["message"] == "Resource owned by a different provisioning partner"

    def test_pay_as_you_go_requires_payment_credentials(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(self._url(self.team.id), data={"service_id": "pay_as_you_go"}, token=token)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "requires_payment_credentials"
