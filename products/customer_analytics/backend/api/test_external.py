from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Team
from posthog.models.utils import generate_random_token_secret

from products.customer_analytics.backend.models.account import AccountAssignment, AccountProperties
from products.customer_analytics.backend.test.factories import create_account


class TestExternalAccountAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["secret_api_token"])
        # Fresh client so requests are unauthenticated unless they carry the Bearer token.
        self.client = APIClient()
        self.account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")
        self.url = "/api/customer_analytics/external/account"

    def _auth_headers(self, token=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.team.secret_api_token}"}

    def _get(self, external_id="acme-1", token=None):
        return self.client.get(self.url, data={"external_id": external_id}, **self._auth_headers(token))

    # -- Authentication ---------------------------------------------------

    def test_get_requires_auth(self):
        response = self.client.get(self.url, data={"external_id": "acme-1"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @parameterized.expand(
        [
            ("no_header", ""),
            ("bad_scheme", "Basic abc123"),
            ("empty_bearer", "Bearer "),
            ("wrong_token", "Bearer phs_wrong_token"),
        ]
    )
    def test_get_rejects_invalid_auth(self, _name, auth_value):
        headers = {"HTTP_AUTHORIZATION": auth_value} if auth_value else {}
        response = self.client.get(self.url, data={"external_id": "acme-1"}, **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_public_api_token(self):
        response = self._get(token=self.team.api_token)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_accepts_backup_token(self):
        backup_token = generate_random_token_secret()
        self.team.secret_api_token_backup = backup_token
        self.team.save(update_fields=["secret_api_token_backup"])
        response = self._get(token=backup_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # -- GET account ------------------------------------------------------

    def test_get_requires_external_id(self):
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_account_not_found(self):
        response = self._get(external_id="does-not-exist")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_account_returns_fields(self):
        response = self._get()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], str(self.account.id))
        self.assertEqual(data["external_id"], "acme-1")
        self.assertEqual(data["name"], "Acme Corp")
        self.assertIn("properties", data)
        self.assertIsNone(data["properties"]["csm"])

    def test_get_account_returns_role_properties(self):
        self.account.properties = AccountProperties(
            csm=AccountAssignment(id=self.user.id, email=self.user.email),
        )
        self.account.save(update_fields=["_properties"])

        response = self._get()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        csm = response.json()["properties"]["csm"]
        self.assertEqual(csm["id"], self.user.id)
        self.assertEqual(csm["email"], self.user.email)

    def test_does_not_leak_accounts_from_other_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_team.secret_api_token = generate_random_token_secret()
        other_team.save(update_fields=["secret_api_token"])

        response = self._get(token=other_team.secret_api_token)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
