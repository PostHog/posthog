from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Organization, Team, User
from posthog.models.utils import generate_random_token_secret

from products.customer_analytics.backend.models import (
    AccountRelationship,
    AccountRelationshipDefinition,
    CustomPropertyValue,
    DisplayType,
)
from products.customer_analytics.backend.models.account import AccountProperties
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition


class TestExternalAccountAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["secret_api_token"])
        # Fresh client so requests are unauthenticated unless they carry the Bearer token.
        self.client = APIClient()
        self.account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")
        self.csm_definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="CSM"
        )
        self.url = "/api/customer_analytics/external/account"
        csp_enabled = patch(
            "products.customer_analytics.backend.presentation.views.external.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.mock_csp_enabled = csp_enabled.start()
        self.addCleanup(csp_enabled.stop)

    def _auth_headers(self, token=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.team.secret_api_token}"}

    def _get(self, external_id="acme-1", token=None):
        return self.client.get(self.url, data={"external_id": external_id}, **self._auth_headers(token))

    def _patch(self, payload, token=None):
        return self.client.patch(self.url, data=payload, format="json", **self._auth_headers(token))

    def _assign_csm(self, user):
        return AccountRelationship.objects.for_team(self.team.id).create(
            team_id=self.team.id, definition=self.csm_definition, account=self.account, user=user
        )

    def _active_csm_user_ids(self):
        return list(
            AccountRelationship.objects.for_team(self.team.id)
            .filter(account=self.account, definition=self.csm_definition, ended_at__isnull=True)
            .values_list("user_id", flat=True)
        )

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

    def test_rejects_team_without_customer_analytics_enabled(self):
        self.mock_csp_enabled.return_value = False
        response = self._get()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

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
        self.assertEqual(data["relationships"], {})

    def test_get_account_returns_active_relationships(self):
        self._assign_csm(self.user)

        response = self._get()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["relationships"],
            {"CSM": [{"user_id": self.user.id, "email": self.user.email}]},
        )

    def test_does_not_leak_accounts_from_other_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_team.secret_api_token = generate_random_token_secret()
        other_team.save(update_fields=["secret_api_token"])

        response = self._get(token=other_team.secret_api_token)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -- PATCH account ----------------------------------------------------

    def test_patch_requires_auth(self):
        response = self.client.patch(self.url, data={"external_id": "acme-1"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_patch_requires_external_id(self):
        response = self._patch({"tags": ["enterprise"]})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_account_not_found(self):
        response = self._patch({"external_id": "does-not-exist", "tags": ["enterprise"]})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_assigns_relationship_and_returns_it(self):
        response = self._patch(
            {"external_id": "acme-1", "relationships": {"CSM": {"type": "user", "id": self.user.id}}}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["relationships"],
            {"CSM": [{"user_id": self.user.id, "email": self.user.email}]},
        )
        self.assertEqual(self._active_csm_user_ids(), [self.user.id])

    def test_patch_null_ends_active_assignment(self):
        self._assign_csm(self.user)

        response = self._patch({"external_id": "acme-1", "relationships": {"CSM": None}})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["relationships"], {})
        self.assertEqual(self._active_csm_user_ids(), [])

    def test_patch_relationships_do_not_touch_properties(self):
        self.account.properties = AccountProperties(stripe_customer_id="cus_123")
        self.account.save(update_fields=["_properties"])

        response = self._patch(
            {"external_id": "acme-1", "relationships": {"CSM": {"type": "user", "id": self.user.id}}}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["properties"]["stripe_customer_id"], "cus_123")

    @parameterized.expand(
        [
            ("role_assignee", {"type": "role", "id": "some-role-uuid"}),
            ("not_an_object", "someone@example.com"),
            ("bad_id", {"type": "user", "id": {"nested": True}}),
        ]
    )
    def test_patch_rejects_invalid_assignee(self, _name, assignee):
        response = self._patch({"external_id": "acme-1", "relationships": {"CSM": assignee}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._active_csm_user_ids(), [])

    def test_patch_rejects_unknown_definition_name(self):
        response = self._patch({"external_id": "acme-1", "relationships": {"AE": {"type": "user", "id": self.user.id}}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "AE: no relationship definition with this name")

    def test_patch_rejects_non_member_user(self):
        other_org = Organization.objects.create(name="Outsiders")
        outsider = User.objects.create_and_join(other_org, "outsider@example.com", None)
        response = self._patch({"external_id": "acme-1", "relationships": {"CSM": {"type": "user", "id": outsider.id}}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "CSM: user is not a member of this organization")
        self.assertEqual(self._active_csm_user_ids(), [])

    def test_patch_adds_tags_by_default(self):
        self._patch({"external_id": "acme-1", "tags": ["enterprise"]})
        response = self._patch({"external_id": "acme-1", "tags": ["priority"]})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["enterprise", "priority"])

    def test_patch_sets_tags_replacing_existing(self):
        self._patch({"external_id": "acme-1", "tags": ["enterprise"]})
        response = self._patch({"external_id": "acme-1", "tags": ["priority"], "tags_mode": "set"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["priority"])

    def test_patch_removes_tags(self):
        self._patch({"external_id": "acme-1", "tags": ["enterprise", "priority"]})
        response = self._patch({"external_id": "acme-1", "tags": ["priority"], "tags_mode": "remove"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["enterprise"])

    def test_patch_does_not_update_other_team_account(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_team.secret_api_token = generate_random_token_secret()
        other_team.save(update_fields=["secret_api_token"])

        response = self._patch({"external_id": "acme-1", "tags": ["enterprise"]}, token=other_team.secret_api_token)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_rolls_back_relationship_assignment_when_tags_fail(self):
        with patch(
            "products.customer_analytics.backend.facade.api._apply_external_tags",
            side_effect=Exception("boom"),
        ):
            response = self._patch(
                {
                    "external_id": "acme-1",
                    "relationships": {"CSM": {"type": "user", "id": self.user.id}},
                    "tags": ["enterprise"],
                }
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._active_csm_user_ids(), [])

    def test_patch_cannot_change_external_id_or_name(self):
        # external_id only identifies the account; renaming/rebinding is not exposed to workflows.
        response = self._patch({"external_id": "acme-1", "name": "Renamed", "new_external_id": "acme-2"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.account.refresh_from_db()
        self.assertEqual(self.account.external_id, "acme-1")
        self.assertEqual(self.account.name, "Acme Corp")


class TestExternalAccountCustomPropertiesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["secret_api_token"])
        self.client = APIClient()
        self.account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")
        self.plan = create_custom_property_definition(team_id=self.team.id, name="Plan", display_type=DisplayType.TEXT)
        self.seats = create_custom_property_definition(
            team_id=self.team.id, name="Seats", display_type=DisplayType.NUMBER
        )
        self.url = "/api/customer_analytics/external/account/custom_property_values"
        csp_enabled = patch(
            "products.customer_analytics.backend.presentation.views.external.posthoganalytics.feature_enabled",
            return_value=True,
        )
        csp_enabled.start()
        self.addCleanup(csp_enabled.stop)

    def _auth_headers(self, token=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.team.secret_api_token}"}

    def _patch(self, payload, token=None):
        return self.client.patch(self.url, data=payload, format="json", **self._auth_headers(token))

    def test_requires_auth(self):
        response = self.client.patch(self.url, data={"external_id": "acme-1", "properties": {}}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_sets_values_by_definition_id(self):
        response = self._patch(
            {"external_id": "acme-1", "properties": {str(self.plan.id): "enterprise", str(self.seats.id): 42}}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        active = CustomPropertyValue.objects.for_team(self.team.id).filter(account=self.account, is_deleted=False)
        self.assertEqual(
            {(v.definition.name, v.value_str, v.value_num) for v in active},
            {
                ("Plan", "enterprise", None),
                ("Seats", None, 42.0),
            },
        )

    def test_unknown_external_id_returns_404(self):
        response = self._patch({"external_id": "missing", "properties": {str(self.plan.id): "x"}})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unknown_definition_id_returns_400(self):
        response = self._patch({"external_id": "acme-1", "properties": {str(uuid4()): "x"}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_non_scalar_value(self):
        response = self._patch({"external_id": "acme-1", "properties": {str(self.plan.id): {"nested": "object"}}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
