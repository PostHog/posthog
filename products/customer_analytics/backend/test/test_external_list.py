from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Organization, Team, User
from posthog.models.utils import generate_random_token_secret

from products.customer_analytics.backend.models.account import AccountAssignment, AccountProperties
from products.customer_analytics.backend.test.factories import create_account


class TestExternalAccountListAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["secret_api_token"])
        # Fresh client so requests are unauthenticated unless they carry the Bearer token.
        self.client = APIClient()
        self.url = "/api/customer_analytics/external/accounts"
        csp_enabled = patch(
            "products.customer_analytics.backend.presentation.views.external.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.mock_csp_enabled = csp_enabled.start()
        self.addCleanup(csp_enabled.stop)

    def _auth_headers(self, token=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.team.secret_api_token}"}

    def _get(self, params=None, token=None):
        return self.client.get(self.url, data=params or {}, **self._auth_headers(token))

    def _assign(self, account, **roles):
        account.properties = AccountProperties(
            **{field: AccountAssignment(id=user.id, email=user.email) for field, user in roles.items()}
        )
        account.save(update_fields=["_properties"])

    # -- Authentication ---------------------------------------------------

    def test_requires_auth(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_public_api_token(self):
        response = self._get(token=self.team.api_token)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_team_without_customer_analytics_enabled(self):
        self.mock_csp_enabled.return_value = False
        response = self._get()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -- Listing ----------------------------------------------------------

    def test_lists_accounts_with_resolved_assignment_names(self):
        self.user.first_name = "Anna"
        self.user.last_name = "Exec"
        self.user.save(update_fields=["first_name", "last_name"])
        account = create_account(team_id=self.team.id, name="Acme", external_id="org-1")
        self._assign(account, account_executive=self.user, csm=self.user)

        response = self._get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsNone(data["next_cursor"])
        self.assertEqual(len(data["results"]), 1)
        row = data["results"][0]
        self.assertEqual(row["external_id"], "org-1")
        self.assertEqual(row["name"], "Acme")
        self.assertEqual(row["account_executive"], {"id": self.user.id, "email": self.user.email, "name": "Anna Exec"})
        self.assertEqual(row["csm"], {"id": self.user.id, "email": self.user.email, "name": "Anna Exec"})
        self.assertIsNone(row["account_owner"])

    def test_deleted_user_yields_stored_email_and_null_name(self):
        account = create_account(team_id=self.team.id, name="Acme", external_id="org-1")
        ghost = User.objects.create_user(email="ghost@x.com", password=None, first_name="Ghost")
        self._assign(account, account_executive=ghost)
        ghost_id = ghost.id
        ghost.delete()

        response = self._get()

        row = response.json()["results"][0]
        self.assertEqual(row["account_executive"], {"id": ghost_id, "email": "ghost@x.com", "name": None})

    def test_excludes_accounts_without_external_id(self):
        no_external = create_account(team_id=self.team.id, name="No external id")
        self._assign(no_external, csm=self.user)
        create_account(team_id=self.team.id, name="Listed", external_id="org-1")

        response = self._get()

        names = [row["name"] for row in response.json()["results"]]
        self.assertEqual(names, ["Listed"])

    def test_assigned_only_filters_to_accounts_with_any_role(self):
        assigned = create_account(team_id=self.team.id, name="Assigned", external_id="org-1")
        self._assign(assigned, csm=self.user)
        # JSON-null roles and empty properties both count as unassigned.
        null_roles = create_account(team_id=self.team.id, name="Null roles", external_id="org-2")
        null_roles._properties = {"csm": None, "account_executive": None}
        null_roles.save(update_fields=["_properties"])
        create_account(team_id=self.team.id, name="Empty", external_id="org-3")

        response = self._get({"assigned_only": "true"})

        names = [row["name"] for row in response.json()["results"]]
        self.assertEqual(names, ["Assigned"])

        response = self._get()
        self.assertEqual(len(response.json()["results"]), 3)

    def test_paginates_with_cursor(self):
        for i in range(3):
            account = create_account(team_id=self.team.id, name=f"Account {i}", external_id=f"org-{i}")
            self._assign(account, csm=self.user)

        page_one = self._get({"limit": 2}).json()
        self.assertEqual(len(page_one["results"]), 2)
        self.assertIsNotNone(page_one["next_cursor"])

        page_two = self._get({"limit": 2, "cursor": page_one["next_cursor"]}).json()
        self.assertEqual(len(page_two["results"]), 1)
        self.assertIsNone(page_two["next_cursor"])

        all_names = [row["name"] for row in page_one["results"] + page_two["results"]]
        self.assertEqual(sorted(all_names), ["Account 0", "Account 1", "Account 2"])

    def test_does_not_leak_accounts_from_other_team(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        create_account(team_id=other_team.id, name="Other team account", external_id="org-other")
        create_account(team_id=self.team.id, name="Mine", external_id="org-1")

        response = self._get()

        names = [row["name"] for row in response.json()["results"]]
        self.assertEqual(names, ["Mine"])

    # -- Validation -------------------------------------------------------

    def test_rejects_invalid_cursor(self):
        response = self._get({"cursor": "not-a-uuid"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_non_integer_limit(self):
        response = self._get({"limit": "abc"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_clamps_limit(self):
        for i in range(2):
            account = create_account(team_id=self.team.id, name=f"Account {i}", external_id=f"org-{i}")
            self._assign(account, csm=self.user)

        response = self._get({"limit": "1000"})
        self.assertEqual(len(response.json()["results"]), 2)

        response = self._get({"limit": "0"})
        self.assertEqual(len(response.json()["results"]), 1)
