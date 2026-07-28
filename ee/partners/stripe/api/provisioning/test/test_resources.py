from datetime import timedelta

from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.utils import generate_random_oauth_access_token

from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, StripeProvisioningTestBase

RESOURCES_URL = f"{BASE_PATH}/provisioning/resources"


class TestResources(StripeProvisioningTestBase):
    def test_create_returns_access_configuration_and_pat(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            RESOURCES_URL, data={"service_id": "analytics", "label_prefix": "Stripe"}, token=token
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "complete"
        assert body["id"] == str(self.team.id)
        assert body["service_id"] == "analytics"
        config = body["complete"]["access_configuration"]
        assert config["api_key"] == self.team.api_token
        assert config["host"]
        assert config["personal_api_key"].startswith("phx_")

        pat = PersonalAPIKey.objects.get(user=self.user)
        assert pat.label == f"Stripe - {self.team.name}"[:40]
        assert pat.scoped_teams == [self.team.id]

        assert TeamProvisioningConfig.objects.get(team=self.team).service_id == "analytics"

    def test_create_with_project_id_is_idempotent(self):
        token = self._get_bearer_token()
        first = self._post_signed_with_bearer(RESOURCES_URL, data={"project_id": "proj_1"}, token=token)
        assert first.status_code == 200
        second = self._post_signed_with_bearer(RESOURCES_URL, data={"project_id": "proj_1"}, token=token)
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        # A project_id provisions a dedicated team, distinct from the consent team.
        assert first.json()["id"] != str(self.team.id)

    def test_unknown_service_rejected(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(RESOURCES_URL, data={"service_id": "nonsense"}, token=token)
        assert res.status_code == 400
        assert res.json() == {
            "status": "error",
            "id": "",
            "error": {"code": "unknown_service", "message": "Unknown service_id: nonsense"},
        }

    @parameterized.expand(
        [
            ("too_long", "x" * 26, "label_prefix must be 25 characters or fewer"),
            ("bidi_override", "evil‮prefix", "label_prefix must not contain control or format characters"),
            ("non_string", 123, "label_prefix must be a string"),
        ]
    )
    def test_invalid_label_prefix_rejected(self, _name, prefix, message):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(RESOURCES_URL, data={"label_prefix": prefix}, token=token)
        assert res.status_code == 400
        assert res.json()["error"] == {"code": "invalid_label_prefix", "message": message}

    def test_pay_as_you_go_requires_payment_credentials(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(RESOURCES_URL, data={"service_id": "pay_as_you_go"}, token=token)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "requires_payment_credentials"

    def test_pay_as_you_go_with_spt_activates_billing(self):
        token = self._get_bearer_token()
        with (
            patch("ee.partners.stripe.api.provisioning.billing._team_has_active_billing", return_value=False),
            patch(
                "ee.partners.stripe.api.provisioning.billing._activate_billing_with_spt", return_value=True
            ) as activate,
        ):
            res = self._post_signed_with_bearer(
                RESOURCES_URL,
                data={
                    "service_id": "pay_as_you_go",
                    "payment_credentials": {"type": "stripe_payment_token", "stripe_payment_token": "spt_1"},
                },
                token=token,
            )
        assert res.status_code == 200
        assert res.json()["service_id"] == "pay_as_you_go"
        activate.assert_called_once()
        assert activate.call_args[0][2] == "spt_1"

    def test_failed_spt_activation_is_reported(self):
        token = self._get_bearer_token()
        with (
            patch("ee.partners.stripe.api.provisioning.billing._team_has_active_billing", return_value=False),
            patch("ee.partners.stripe.api.provisioning.billing._activate_billing_with_spt", return_value=False),
        ):
            res = self._post_signed_with_bearer(
                RESOURCES_URL,
                data={
                    "service_id": "analytics",
                    "payment_credentials": {"type": "stripe_payment_token", "stripe_payment_token": "spt_1"},
                },
                token=token,
            )
        assert res.status_code == 400
        assert res.json() == {
            "status": "error",
            "id": str(self.team.id),
            "error": {"code": "requires_payment_credentials", "message": "Billing activation failed"},
        }

    def test_detail_returns_resource(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(f"{RESOURCES_URL}/{self.team.id}", token=token)
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "complete"
        assert body["id"] == str(self.team.id)
        assert body["complete"]["access_configuration"]["api_key"] == self.team.api_token

    @parameterized.expand(
        [
            ("non_numeric", "abc", 400, "invalid_resource_id"),
            ("out_of_scope", "999999", 403, "forbidden"),
        ]
    )
    def test_detail_rejects_bad_resource_ids(self, _name, resource_id, status, code):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(f"{RESOURCES_URL}/{resource_id}", token=token)
        assert res.status_code == status
        body = res.json()
        assert body["status"] == "error"
        assert body["id"] == resource_id
        assert body["error"]["code"] == code

    @parameterized.expand(
        [
            ("missing", None, "Missing bearer token"),
            ("unknown", "pha_bogus", "Invalid access token"),
        ]
    )
    def test_bearer_required(self, _name, token, message):
        if token is None:
            res = self.client.get(f"{RESOURCES_URL}/{self.team.id}", HTTP_API_VERSION="0.1d")
        else:
            res = self._get_signed_with_bearer(f"{RESOURCES_URL}/{self.team.id}", token=token)
        assert res.status_code == 401
        assert res.json() == {
            "status": "error",
            "id": "",
            "error": {"code": "unauthorized", "message": message},
        }

    def test_signature_required_even_with_valid_bearer(self):
        token = self._get_bearer_token()
        res = self.client.get(
            f"{RESOURCES_URL}/{self.team.id}",
            HTTP_API_VERSION="0.1d",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert res.status_code == 401
        assert res.json() == {"error": {"code": "invalid_signature", "message": "Signature verification failed"}}

    def test_bearer_from_another_app_rejected(self):
        # Authorization is by identity alone: a token for any app other than the
        # Stripe Projects app is rejected regardless of its config.
        other_app = self._create_other_partner_app()
        token_value = generate_random_oauth_access_token(None)
        OAuthAccessToken.objects.create(
            application=other_app,
            token=token_value,
            user=self.user,
            expires=timezone.now() + timedelta(days=1),
            scope="query:read",
            scoped_teams=[self.team.id],
        )

        res = self._get_signed_with_bearer(f"{RESOURCES_URL}/{self.team.id}", token=token_value)
        assert res.status_code == 401
        assert res.json() == {
            "status": "error",
            "id": "",
            "error": {"code": "unauthorized", "message": "Authentication failed"},
        }
