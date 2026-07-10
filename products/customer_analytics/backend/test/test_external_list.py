from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Organization, Team, User
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import generate_random_token_secret, hash_key_value, mask_key_value

from products.customer_analytics.backend.models import AccountRelationship, AccountRelationshipDefinition
from products.customer_analytics.backend.test.factories import create_account

ENDED_AT = datetime(2026, 1, 1, tzinfo=UTC)


class TestExternalAccountListAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.psak_token = self._create_psak_token(scopes=["account:read"])
        # Fresh client so requests are unauthenticated unless they carry the Bearer token.
        self.client = APIClient()
        self.url = "/api/customer_analytics/external/accounts"
        self.csm_definition = self._create_definition("CSM")
        csp_enabled = patch(
            "products.customer_analytics.backend.presentation.views.external.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.mock_csp_enabled = csp_enabled.start()
        self.addCleanup(csp_enabled.stop)

    def _create_psak_token(self, scopes, label="external-list"):
        token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label=label,
            mask_value=mask_key_value(token),
            secure_value=hash_key_value(token),
            scopes=scopes,
        )
        return token

    def _create_definition(self, name, **kwargs):
        return AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name=name, **kwargs
        )

    def _assign(self, account, user, definition=None, ended_at=None):
        return AccountRelationship.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            account=account,
            definition=definition or self.csm_definition,
            user=user,
            ended_at=ended_at,
        )

    def _auth_headers(self, token=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.psak_token}"}

    def _get(self, params=None, token=None):
        return self.client.get(self.url, data=params or {}, **self._auth_headers(token))

    # -- Authentication ---------------------------------------------------

    def test_requires_auth(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_public_api_token(self):
        response = self._get(token=self.team.api_token)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_team_secret_api_token(self):
        # The team-wide secret token is readable by any project member, so it must
        # not unlock this bulk export; only a scoped project secret API key may.
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["secret_api_token"])

        response = self._get(token=self.team.secret_api_token)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_key_without_account_read_scope(self):
        token = self._create_psak_token(scopes=["endpoint:read"], label="wrong-scope")

        response = self._get(token=token)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_rejects_team_without_customer_analytics_enabled(self):
        self.mock_csp_enabled.return_value = False
        response = self._get()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -- Listing ----------------------------------------------------------

    def test_lists_accounts_with_relationship_assignments(self):
        self.user.first_name = "Anna"
        self.user.last_name = "Exec"
        self.user.save(update_fields=["first_name", "last_name"])
        colleague = User.objects.create_and_join(self.organization, "aaa@x.com", None)
        ae_definition = self._create_definition("Account executive", is_single_holder=False)
        account = create_account(team_id=self.team.id, name="Acme", external_id="org-1")
        self._assign(account, self.user)
        self._assign(account, self.user, definition=ae_definition)
        self._assign(account, colleague, definition=ae_definition)

        response = self._get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsNone(data["next_cursor"])
        self.assertEqual(len(data["results"]), 1)
        row = data["results"][0]
        self.assertEqual(row["external_id"], "org-1")
        self.assertEqual(row["name"], "Acme")
        self.assertEqual(
            row["relationships"],
            {
                "Account executive": [
                    {"user_id": colleague.id, "email": "aaa@x.com", "name": None},
                    {"user_id": self.user.id, "email": self.user.email, "name": "Anna Exec"},
                ],
                "CSM": [{"user_id": self.user.id, "email": self.user.email, "name": "Anna Exec"}],
            },
        )

    def test_omits_ended_and_userless_assignments(self):
        account = create_account(team_id=self.team.id, name="Acme", external_id="org-1")
        self._assign(account, self.user, ended_at=ENDED_AT)
        ghost = User.objects.create_user(email="ghost@x.com", password=None, first_name="Ghost")
        self._assign(account, ghost, definition=self._create_definition("Account executive"))
        # Deleting the user SET_NULLs the relationship's user; the row must not surface.
        ghost.delete()

        response = self._get()

        row = response.json()["results"][0]
        self.assertEqual(row["relationships"], {})

    def test_excludes_accounts_without_external_id(self):
        no_external = create_account(team_id=self.team.id, name="No external id")
        self._assign(no_external, self.user)
        blank_external = create_account(team_id=self.team.id, name="Blank external id", external_id="")
        self._assign(blank_external, self.user)
        create_account(team_id=self.team.id, name="Listed", external_id="org-1")

        response = self._get()

        names = [row["name"] for row in response.json()["results"]]
        self.assertEqual(names, ["Listed"])

    def test_assigned_only_filters_to_accounts_with_an_active_assignment(self):
        assigned = create_account(team_id=self.team.id, name="Assigned", external_id="org-1")
        self._assign(assigned, self.user)
        ended = create_account(team_id=self.team.id, name="Ended", external_id="org-2")
        self._assign(ended, self.user, ended_at=ENDED_AT)
        create_account(team_id=self.team.id, name="Never assigned", external_id="org-3")

        response = self._get({"assigned_only": "true"})

        names = [row["name"] for row in response.json()["results"]]
        self.assertEqual(names, ["Assigned"])

        response = self._get()
        self.assertEqual(len(response.json()["results"]), 3)

    def test_paginates_with_cursor(self):
        for i in range(3):
            account = create_account(team_id=self.team.id, name=f"Account {i}", external_id=f"org-{i}")
            self._assign(account, self.user)

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

    @parameterized.expand(
        [
            ("invalid_cursor", {"cursor": "not-a-uuid"}),
            ("non_integer_limit", {"limit": "abc"}),
            ("invalid_assigned_only", {"assigned_only": "banana"}),
        ]
    )
    def test_rejects_invalid_query_param(self, _name, params):
        response = self._get(params)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_clamps_limit(self):
        for i in range(2):
            create_account(team_id=self.team.id, name=f"Account {i}", external_id=f"org-{i}")

        response = self._get({"limit": "1000"})
        self.assertEqual(len(response.json()["results"]), 2)

        response = self._get({"limit": "0"})
        self.assertEqual(len(response.json()["results"]), 1)
