from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.utils import generate_random_token_personal, generate_random_token_secret, hash_key_value
from posthog.test.api_keys import create_project_secret_api_key

from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.facade import api as facade
from products.customer_analytics.backend.models import AccountRelationship, AccountRelationshipDefinition
from products.customer_analytics.backend.test.factories import create_account, enroll_account

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
            "products.customer_analytics.backend.presentation.views.external._customer_analytics_enabled",
            return_value=True,
        )
        self.mock_csp_enabled = csp_enabled.start()
        self.addCleanup(csp_enabled.stop)

    def _create_psak_token(self, scopes, label="external-list"):
        _, token = create_project_secret_api_key(self.team, label=label, scopes=scopes)
        return token

    def _create_personal_token(self, scopes: list[str]) -> tuple[PersonalAPIKey, str]:
        token = generate_random_token_personal()
        key = PersonalAPIKey.objects.create(
            user=self.user,
            label="external-list",
            secure_value=hash_key_value(token),
            scopes=scopes,
            scoped_teams=[self.team.id],
        )
        return key, token

    def _create_definition(self, name, **kwargs):
        return AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name=name, **kwargs
        )

    def _enrolled_account(self, *, name, external_id, definition, **kwargs):
        account = create_account(team_id=self.team.id, name=name, external_id=external_id, **kwargs)
        enroll_account(account, definition, controlled_at=ENDED_AT)
        return account

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

    @contextmanager
    def _rate_limits(self, *, key_rate: str, team_rate: str) -> Iterator[None]:
        with (
            patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True),
            patch(
                "products.customer_analytics.backend.presentation.views.external.ExternalAccountListBurstThrottle.rate",
                key_rate,
            ),
            patch(
                "products.customer_analytics.backend.presentation.views.external.ExternalAccountListSustainedThrottle.rate",
                key_rate,
            ),
            patch(
                "products.customer_analytics.backend.presentation.views.external.ExternalAccountListTeamBurstThrottle.rate",
                team_rate,
            ),
            patch(
                "products.customer_analytics.backend.presentation.views.external.ExternalAccountListTeamSustainedThrottle.rate",
                team_rate,
            ),
        ):
            yield

    # -- Authentication ---------------------------------------------------

    def test_requires_auth(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_public_api_token(self):
        response = self._get(token=self.team.api_token)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_team_secret_api_token(self):
        # The team-wide secret token is readable by any project member, so it must
        # not unlock this bulk export without API scope checks.
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["secret_api_token"])

        response = self._get(token=self.team.secret_api_token)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @parameterized.expand([("project",), ("personal",)])
    def test_rejects_key_without_account_read_scope(self, key_type: str) -> None:
        if key_type == "personal":
            _, token = self._create_personal_token(scopes=["endpoint:read"])
        else:
            token = self._create_psak_token(scopes=["endpoint:read"], label="wrong-scope")

        response = self._get(params={"project_id": self.team.id}, token=token)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        message = "API key missing required scope 'account:read'"
        self.assertEqual(
            response.json(), self.permission_denied_response(message) if key_type == "personal" else {"error": message}
        )

    @parameterized.expand([("missing", None), ("invalid", "abc"), ("negative", -1)])
    def test_personal_key_requires_valid_project_id(self, _name: str, project_id: str | int | None) -> None:
        _, token = self._create_personal_token(scopes=["account:read"])
        response = self._get(params={} if project_id is None else {"project_id": project_id}, token=token)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_personal_key_returns_not_found_for_deleted_project(self) -> None:
        project = Team.objects.create(organization=self.organization, name="Deleted project")
        project_id = project.id
        project.delete()
        _, token = self._create_personal_token(scopes=["account:read"])

        response = self._get(params={"project_id": project_id}, token=token)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json(), self.not_found_response("Project not found."))

    @parameterized.expand([("project_scope",), ("organization_scope",), ("membership",), ("resource_access",)])
    def test_personal_key_enforces_access(self, restriction: str) -> None:
        key, token = self._create_personal_token(scopes=["account:read"])
        if restriction == "project_scope":
            other_team = Team.objects.create(organization=self.organization, name="Other project")
            key.scoped_teams = [other_team.id]
            key.save()
        elif restriction == "organization_scope":
            other_org = Organization.objects.create(name="Other organization")
            key.scoped_organizations = [str(other_org.id)]
            key.save()
        elif restriction == "membership":
            OrganizationMembership.objects.filter(user=self.user, organization=self.organization).delete()
        else:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
                {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
            ]
            self.organization.save()
            membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
            membership.level = OrganizationMembership.Level.MEMBER
            membership.save()
            AccessControl.objects.create(
                team=self.team, resource="customer_analytics", access_level="none", organization_member=membership
            )

        response = self._get(params={"project_id": self.team.id}, token=token)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @parameterized.expand([("all", False), ("managed", True)])
    def test_personal_key_filters_account_access_before_pagination(self, _name: str, managed_only: bool) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()
        hidden = create_account(team_id=self.team.id, name="Hidden", external_id="hidden-account")
        visible = create_account(team_id=self.team.id, name="Visible", external_id="visible-account")
        if managed_only:
            self.csm_definition.is_controlled = True
            self.csm_definition.save(update_fields=["is_controlled"])
            enroll_account(hidden, self.csm_definition, controlled_at=ENDED_AT)
            enroll_account(visible, self.csm_definition, controlled_at=ENDED_AT)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(hidden.id),
            access_level="none",
            organization_member=membership,
        )
        _, token = self._create_personal_token(scopes=["account:read"])

        response = self._get(
            params={"project_id": self.team.id, "limit": 1, "managed_only": str(managed_only).lower()}, token=token
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["external_id"] for row in response.json()["results"]], [visible.external_id])
        self.assertIsNone(response.json()["next_cursor"])

    def test_personal_key_respects_feature_gate(self) -> None:
        _, token = self._create_personal_token(scopes=["account:read"])
        self.mock_csp_enabled.return_value = False
        self.assertEqual(
            self._get(params={"project_id": self.team.id}, token=token).status_code, status.HTTP_401_UNAUTHORIZED
        )

    def test_project_key_cannot_select_another_project(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        self.assertEqual(self._get(params={"project_id": other_team.id}).status_code, status.HTTP_403_FORBIDDEN)

    def test_disabled_feature_does_not_reveal_key_validity_or_scopes(self):
        wrong_scope_token = self._create_psak_token(scopes=["endpoint:read"], label="wrong-scope-disabled")
        self.mock_csp_enabled.return_value = False

        for token in [self.psak_token, wrong_scope_token, generate_random_token_secret()]:
            with self.subTest(token=token):
                response = self._get(token=token)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
                self.assertEqual(response.json(), {"error": "Missing or invalid API key"})

    def test_rate_limit_is_shared_across_project_secret_api_keys(self):
        cache.clear()
        self.addCleanup(cache.clear)
        second_token = self._create_psak_token(scopes=["account:read"], label="second-key")

        with self._rate_limits(key_rate="100/minute", team_rate="1/minute"):
            self.assertEqual(self._get().status_code, status.HTTP_200_OK)
            self.assertEqual(self._get(token=second_token).status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @parameterized.expand(
        [("project", "project"), ("personal", "personal"), ("project", "personal"), ("personal", "project")]
    )
    def test_invalid_tokens_share_ip_rate_limit(self, first_key_type: str, second_key_type: str) -> None:
        cache.clear()
        self.addCleanup(cache.clear)
        token_generators = {"project": generate_random_token_secret, "personal": generate_random_token_personal}

        with self._rate_limits(key_rate="1/minute", team_rate="100/minute"):
            self.assertEqual(
                self._get(token=token_generators[first_key_type]()).status_code,
                status.HTTP_401_UNAUTHORIZED,
            )
            self.assertEqual(
                self._get(token=token_generators[second_key_type]()).status_code,
                status.HTTP_429_TOO_MANY_REQUESTS,
            )

    def test_disabled_feature_uses_invalid_token_rate_bucket(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.mock_csp_enabled.return_value = False

        with self._rate_limits(key_rate="1/minute", team_rate="100/minute"):
            self.assertEqual(self._get().status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(
                self._get(token=generate_random_token_secret()).status_code,
                status.HTTP_429_TOO_MANY_REQUESTS,
            )

    # -- Listing ----------------------------------------------------------

    @parameterized.expand([("project",), ("personal_read",), ("personal_write",), ("personal_all",)])
    def test_lists_accounts_with_relationship_assignments(self, key_type: str) -> None:
        self.user.first_name = "Anna"
        self.user.last_name = "Exec"
        self.user.save(update_fields=["first_name", "last_name"])
        colleague = User.objects.create_and_join(self.organization, "aaa@x.com", None)
        ae_definition = self._create_definition("Account executive", is_single_holder=False)
        account = create_account(
            team_id=self.team.id,
            name="Acme",
            external_id="org-1",
            churned_at=datetime(2026, 8, 1, 12, 30, tzinfo=UTC),
        )
        self._assign(account, self.user)
        self._assign(account, self.user, definition=ae_definition)
        self._assign(account, colleague, definition=ae_definition)

        if key_type == "project":
            response = self._get()
        else:
            scope = {"personal_read": "account:read", "personal_write": "account:write", "personal_all": "*"}[key_type]
            _, token = self._create_personal_token(scopes=[scope])
            response = self._get(params={"project_id": self.team.id}, token=token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsNone(data["next_cursor"])
        self.assertEqual(len(data["results"]), 1)
        row = data["results"][0]
        self.assertEqual(row["external_id"], "org-1")
        self.assertEqual(row["name"], "Acme")
        self.assertEqual(row["churned_at"], "2026-08-01T12:30:00Z")
        self.assertIsNone(row["ignored_at"])
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

    @parameterized.expand(
        [
            ("membership_removed",),
            ("other_organization_only",),
        ]
    )
    def test_omits_relationship_users_without_current_org_membership(self, membership_state: str) -> None:
        if membership_state == "membership_removed":
            relationship_user = User.objects.create_and_join(self.organization, "former@x.com", None)
            OrganizationMembership.objects.filter(
                organization=self.organization,
                user=relationship_user,
            ).delete()
        else:
            other_organization = Organization.objects.create(name="Other organization")
            relationship_user = User.objects.create_and_join(other_organization, "other-org@x.com", None)

        relationship_user.first_name = "Former"
        relationship_user.last_name = "Member"
        relationship_user.save(update_fields=["first_name", "last_name"])

        account = create_account(team_id=self.team.id, name="Acme", external_id="org-1")
        self._assign(account, relationship_user)

        response = self._get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        (row,) = response.json()["results"]
        self.assertEqual(row["external_id"], "org-1")
        self.assertEqual(row["relationships"], {})

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

    def test_excludes_ignored_accounts_by_default(self):
        create_account(team_id=self.team.id, name="Tracked", external_id="tracked")
        create_account(
            team_id=self.team.id,
            name="Ignored",
            external_id="ignored",
            ignored_at=datetime(2026, 8, 2, 12, 30, tzinfo=UTC),
        )

        default_response = self._get()
        included_response = self._get({"include_ignored": "true"})

        self.assertEqual(
            [row["name"] for row in default_response.json()["results"]],
            ["Tracked"],
        )
        self.assertEqual(
            {row["name"] for row in included_response.json()["results"]},
            {"Tracked", "Ignored"},
        )
        ignored_row = next(row for row in included_response.json()["results"] if row["name"] == "Ignored")
        self.assertEqual(ignored_row["ignored_at"], "2026-08-02T12:30:00Z")

    def test_excludes_accounts_without_external_id(self):
        no_external = create_account(team_id=self.team.id, name="No external id")
        self._assign(no_external, self.user)
        blank_external = create_account(team_id=self.team.id, name="Blank external id", external_id="")
        self._assign(blank_external, self.user)
        create_account(team_id=self.team.id, name="Listed", external_id="org-1")

        response = self._get()

        names = [row["name"] for row in response.json()["results"]]
        self.assertEqual(names, ["Listed"])

    def test_managed_only_returns_managed_accounts_including_cleared_roles(self):
        self.csm_definition.is_controlled = True
        self.csm_definition.save(update_fields=["is_controlled"])
        onboarding_definition = self._create_definition("Onboarding manager", is_controlled=True)
        assigned = self._enrolled_account(name="Assigned", external_id="assigned", definition=self.csm_definition)
        self._assign(assigned, self.user)
        self._enrolled_account(name="Cleared", external_id="cleared", definition=self.csm_definition)
        self._enrolled_account(
            name="Ignored", external_id="ignored", definition=self.csm_definition, ignored_at=ENDED_AT
        )
        self._enrolled_account(name="Onboarding", external_id="onboarding", definition=onboarding_definition)
        legacy = create_account(team_id=self.team.id, name="Legacy", external_id="legacy")
        self._assign(legacy, self.user)

        response = self._get({"managed_only": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        by_external_id = {
            row["external_id"]: {role["definition_name"]: role for role in row["ownership"]["roles"]}
            for row in response.json()["results"]
        }
        self.assertEqual(set(by_external_id), {"assigned", "cleared", "ignored", "onboarding"})
        self.assertEqual(by_external_id["assigned"]["CSM"]["state"], "assigned")
        self.assertEqual(by_external_id["assigned"]["CSM"]["holder"]["email"], self.user.email)
        self.assertEqual(by_external_id["assigned"]["Onboarding manager"]["state"], "unmanaged")
        self.assertEqual(by_external_id["cleared"]["CSM"]["state"], "cleared")
        self.assertIsNone(by_external_id["cleared"]["CSM"]["holder"])
        self.assertEqual(by_external_id["onboarding"]["Onboarding manager"]["state"], "cleared")
        self.assertEqual(by_external_id["onboarding"]["CSM"]["state"], "unmanaged")

    def test_ownership_block_costs_a_fixed_number_of_queries(self):
        definitions = [self._create_definition(name, is_controlled=True) for name in ("AE", "Onboarding", "Support")]
        accounts = [create_account(team_id=self.team.id, name=f"Account {i}", external_id=f"org-{i}") for i in range(3)]
        for account in accounts:
            for definition in definitions:
                enroll_account(account, definition, controlled_at=ENDED_AT)
                self._assign(account, self.user, definition=definition)

        with CaptureQueriesContext(connection) as one_account:
            facade.list_external_accounts(self.team.id, organization_id=self.organization.id, limit=1)
        with CaptureQueriesContext(connection) as three_accounts:
            page = facade.list_external_accounts(self.team.id, organization_id=self.organization.id, limit=3)

        self.assertEqual(len(three_accounts.captured_queries), len(one_account.captured_queries))
        self.assertEqual({len(item.ownership.roles) for item in page.results}, {3})

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

    def test_assigned_only_excludes_accounts_assigned_only_to_another_organization_member(self) -> None:
        other_organization = Organization.objects.create(name="Other organization")
        relationship_user = User.objects.create_and_join(other_organization, "other-org@x.com", None)
        account = create_account(team_id=self.team.id, name="Acme", external_id="org-1")
        self._assign(account, relationship_user)

        response = self._get({"assigned_only": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

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
        self.assertEqual(set(response.json()), {"error"})
        self.assertIn(next(iter(params)), response.json()["error"])

    def test_clamps_limit(self):
        for i in range(2):
            create_account(team_id=self.team.id, name=f"Account {i}", external_id=f"org-{i}")

        response = self._get({"limit": "1000"})
        self.assertEqual(len(response.json()["results"]), 2)

        response = self._get({"limit": "0"})
        self.assertEqual(len(response.json()["results"]), 1)
