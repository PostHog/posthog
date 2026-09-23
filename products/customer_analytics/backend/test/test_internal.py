from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from prometheus_client import REGISTRY
from rest_framework import status
from rest_framework.test import APIClient

from posthog.jwt import PosthogJwtAudience
from posthog.models.utils import generate_random_token_secret
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.models import CustomPropertyValue
from products.customer_analytics.backend.presentation.views.internal import CUSTOMER_ANALYTICS_ACCOUNTS_PURPOSE
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition

# Signed with this route's key but carrying another surface's audience — a token minted for a
# different purpose must never authenticate here even when the signing key checks out.
OTHER_AUDIENCE_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.CONVERSATIONS_TICKETS,
    settings_name="CUSTOMER_ANALYTICS_ACCOUNTS_JWT_SECRETS",
)


class TestInternalAccountAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["secret_api_token"])
        self.client = APIClient()
        self.account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")
        self.url = f"/api/projects/{self.team.id}/internal/customer_analytics/account"
        csp_enabled = patch(
            "products.customer_analytics.backend.presentation.views.external.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.mock_csp_enabled = csp_enabled.start()
        self.addCleanup(csp_enabled.stop)

    def _claims(self, external_id: str = "acme-1") -> dict:
        return {"team_id": self.team.id, "external_id": external_id}

    def _headers(self, claims: dict | None = None) -> dict:
        return self._bearer(CUSTOMER_ANALYTICS_ACCOUNTS_PURPOSE.mint(claims if claims is not None else self._claims()))

    @staticmethod
    def _bearer(token: str) -> dict:
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_get_returns_account_for_minted_token(self):
        response = self.client.get(self.url, data={"external_id": "acme-1"}, **self._headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["external_id"], "acme-1")

    def test_post_creates_account_pinned_to_the_claim(self):
        response = self.client.post(
            self.url,
            {"external_id": "acme-new"},
            format="json",
            **self._headers(self._claims("acme-new")),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["external_id"], "acme-new")

    def test_patch_updates_account(self):
        response = self.client.patch(
            self.url,
            {"external_id": "acme-1", "tags": ["vip"]},
            format="json",
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["vip"])

    def test_patch_sets_custom_property_values(self):
        definition = create_custom_property_definition(team_id=self.team.id, name="Tier")
        response = self.client.patch(
            f"{self.url}/custom_property_values",
            {"external_id": "acme-1", "properties": {str(definition.id): "gold"}},
            format="json",
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        values = CustomPropertyValue.objects.for_team(self.team.id).filter(account=self.account, is_deleted=False)
        self.assertEqual([v.value_str for v in values], ["gold"])

    @parameterized.expand(
        [
            (
                "token_for_another_team",
                lambda self: self._headers({"team_id": self.team.id + 1, "external_id": "acme-1"}),
                status.HTTP_401_UNAUTHORIZED,
            ),
            (
                "legacy_secret_api_token",
                lambda self: {"HTTP_AUTHORIZATION": f"Bearer {self.team.secret_api_token}"},
                status.HTTP_401_UNAUTHORIZED,
            ),
            (
                "expired_token",
                lambda self: self._bearer(
                    CUSTOMER_ANALYTICS_ACCOUNTS_PURPOSE.mint(self._claims(), ttl=timedelta(minutes=-1))
                ),
                status.HTTP_401_UNAUTHORIZED,
            ),
            (
                "token_for_another_purpose",
                lambda self: self._bearer(OTHER_AUDIENCE_PURPOSE.mint(self._claims())),
                status.HTTP_401_UNAUTHORIZED,
            ),
            (
                "missing_external_id_claim",
                lambda self: self._headers({"team_id": self.team.id}),
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "token_for_another_account",
                lambda self: self._headers(self._claims("someone-else")),
                status.HTTP_403_FORBIDDEN,
            ),
            ("no_credentials", lambda self: {}, status.HTTP_401_UNAUTHORIZED),
        ]
    )
    def test_rejected_credentials(self, _name, make_headers, expected_status):
        headers = make_headers(self)
        get_response = self.client.get(self.url, data={"external_id": "acme-1"}, **headers)
        self.assertEqual(get_response.status_code, expected_status)
        patch_response = self.client.patch(
            self.url, {"external_id": "acme-1", "tags": ["vip"]}, format="json", **headers
        )
        self.assertEqual(patch_response.status_code, expected_status)
        self.assertEqual(self.account.tagged_items.count(), 0)

    def test_missing_claim_does_not_match_an_account_named_none(self):
        # A missing claim stringified would read "None"; it must never authorize an account
        # whose external_id is literally that.
        create_account(team_id=self.team.id, name="Edge", external_id="None")
        response = self.client.get(self.url, data={"external_id": "None"}, **self._headers({"team_id": self.team.id}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_whitespace_padded_claim_matches_like_the_legacy_route(self):
        # The request id is stripped before comparison; the claim must be stripped the same
        # way or a padded id would 403 here while succeeding on the legacy route.
        response = self.client.get(
            self.url,
            data={"external_id": " acme-1 "},
            **self._headers({"team_id": self.team.id, "external_id": " acme-1 "}),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unexpected_update_failure_returns_500(self):
        # UPDATE_FAILED only comes from the facade's blanket except (server fault); a 400
        # would stop the CDP fetch layer from retrying a transient database error.
        failed = contracts.ExternalAccountUpdateResult(error=contracts.ExternalAccountUpdateError.UPDATE_FAILED)
        with patch(
            "products.customer_analytics.backend.presentation.views.account_actions.facade.update_external_account",
            return_value=failed,
        ):
            response = self.client.patch(
                self.url, {"external_id": "acme-1", "tags": ["vip"]}, format="json", **self._headers()
            )
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_request_external_id_must_match_the_claim(self):
        # A token pinned to one account must not read or write another, even in the same team.
        response = self.client.get(self.url, data={"external_id": "someone-else"}, **self._headers())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unprovisioned_secret_rejects_even_a_well_formed_token(self):
        headers = self._headers()
        with override_settings(CUSTOMER_ANALYTICS_ACCOUNTS_JWT_SECRETS=[]):
            response = self.client.get(self.url, data={"external_id": "acme-1"}, **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_analytics_disabled_is_rejected(self):
        self.mock_csp_enabled.return_value = False
        response = self.client.get(self.url, data={"external_id": "acme-1"}, **self._headers())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_get_increments_the_scoped_jwt_counter(self):
        labels = {"auth_method": "scoped_jwt", "http_method": "get"}
        before = REGISTRY.get_sample_value("posthog_customer_analytics_account_action_auth_total", labels) or 0
        self.client.get(self.url, data={"external_id": "acme-1"}, **self._headers())
        after = REGISTRY.get_sample_value("posthog_customer_analytics_account_action_auth_total", labels)
        self.assertEqual(after, before + 1)
