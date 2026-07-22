from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, StripeProvisioningTestBase

RESOURCES_URL = f"{BASE_PATH}/provisioning/resources"


class TestRemoveAndRotate(StripeProvisioningTestBase):
    def test_rotate_credentials_issues_new_api_key_and_pat(self):
        token = self._get_bearer_token()
        original_api_key = self.team.api_token

        res = self._post_signed_with_bearer(
            f"{RESOURCES_URL}/{self.team.id}/rotate_credentials", data={"label_prefix": "Rotated"}, token=token
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "complete"
        rotated_api_key = body["complete"]["access_configuration"]["api_key"]
        assert rotated_api_key != original_api_key
        self.team.refresh_from_db()
        assert self.team.api_token == rotated_api_key
        assert body["complete"]["access_configuration"]["personal_api_key"].startswith("phx_")
        assert PersonalAPIKey.objects.filter(user=self.user, label__startswith="Rotated - ").exists()

    def test_rotate_rejects_invalid_label_prefix_with_resource_id(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"{RESOURCES_URL}/{self.team.id}/rotate_credentials", data={"label_prefix": "x" * 26}, token=token
        )
        assert res.status_code == 400
        assert res.json() == {
            "status": "error",
            "id": str(self.team.id),
            "error": {"code": "invalid_label_prefix", "message": "label_prefix must be 25 characters or fewer"},
        }

    def test_remove_detaches_resource_and_strips_token_scope(self):
        token = self._get_bearer_token()
        create = self._post_signed_with_bearer(RESOURCES_URL, data={"service_id": "analytics"}, token=token)
        assert create.status_code == 200
        assert TeamProvisioningConfig.objects.filter(team=self.team).exists()

        res = self._post_signed_with_bearer(f"{RESOURCES_URL}/{self.team.id}/remove", token=token)
        assert res.status_code == 200
        assert res.json() == {"status": "removed", "id": str(self.team.id)}
        assert not TeamProvisioningConfig.objects.filter(team=self.team).exists()

        # The team left the token's scope; since it was the only scoped team the
        # token itself is gone, so further calls are unauthorized.
        detail = self._get_signed_with_bearer(f"{RESOURCES_URL}/{self.team.id}", token=token)
        assert detail.status_code == 401
