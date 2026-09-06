from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.auth import PersonalAPIKeyAuthentication, ProjectSecretAPIKeyAuthentication
from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from ee.billing.grants import BillingEntitlement, effective_billing_grants

OWNER = OrganizationMembership.Level.OWNER
ADMIN = OrganizationMembership.Level.ADMIN
MEMBER = OrganizationMembership.Level.MEMBER


def _personal_key_authenticator(user: User, scopes: list[str], scoped_teams=None, scoped_organizations=None):
    key = PersonalAPIKey.objects.create(
        user=user,
        label="test",
        secure_value=hash_key_value(generate_random_token_personal()),
        scopes=scopes,
        scoped_teams=scoped_teams,
        scoped_organizations=scoped_organizations,
    )
    authenticator = PersonalAPIKeyAuthentication()
    authenticator.personal_api_key = key
    return authenticator


def _project_secret_key_authenticator(team: Team, scopes: list[str]):
    key = ProjectSecretAPIKey.objects.create(team=team, label="deploy", secure_value="x", scopes=scopes)
    authenticator = ProjectSecretAPIKeyAuthentication()
    authenticator.project_secret_api_key = key
    return authenticator


class TestEffectiveBillingGrants(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization, name="second")
        owner_only = patch("ee.billing.grants._owner_only_billing_enabled", return_value=False)
        member_read = patch("ee.billing.grants._member_billing_usage_spend_read_access_enabled", return_value=False)
        self.owner_only = owner_only.start()
        self.member_read = member_read.start()
        self.addCleanup(owner_only.stop)
        self.addCleanup(member_read.stop)

    def _set_level(self, level):
        self.organization_membership.level = level
        self.organization_membership.save()

    def _grants(self, authenticator=None):
        return effective_billing_grants(organization=self.organization, user=self.user, authenticator=authenticator)

    def test_owner_session_gets_full_access_for_the_whole_organization(self):
        self._set_level(OWNER)
        grants = self._grants()
        self.assertEqual(grants.sub, f"user:{self.user.distinct_id}")
        self.assertEqual(grants.scope, ["billing:read"])
        self.assertEqual(grants.roles, ["owner"])
        self.assertEqual(grants.entitlements, [BillingEntitlement.FULL_ACCESS.value])
        self.assertIsNone(grants.projects)

    @parameterized.expand(
        [
            ("owner_only_off", False, BillingEntitlement.FULL_ACCESS),
            ("owner_only_on", True, BillingEntitlement.MEMBER),
            ("owner_only_unknown", None, BillingEntitlement.MEMBER),
        ]
    )
    def test_admin_depends_on_owner_only_billing(self, _, flag_state, expected):
        self._set_level(ADMIN)
        self.owner_only.return_value = flag_state
        grants = self._grants()
        self.assertEqual(grants.roles, ["admin"])
        self.assertEqual(grants.entitlements, [expected.value])

    @parameterized.expand(
        [
            ("read_flag_on", False, True, BillingEntitlement.USAGE_READ),
            ("read_flag_off", False, False, BillingEntitlement.MEMBER),
            ("owner_only_on_beats_read_flag", True, True, BillingEntitlement.MEMBER),
        ]
    )
    def test_member_depends_on_both_flags(self, _, owner_only, member_read, expected):
        self._set_level(MEMBER)
        self.owner_only.return_value = owner_only
        self.member_read.return_value = member_read
        grants = self._grants()
        self.assertEqual(grants.roles, ["member"])
        self.assertEqual(grants.entitlements, [expected.value])

    def test_non_member_gets_nothing(self):
        outsider = User.objects.create_user(email="outsider@example.com", password="x", first_name="o")
        grants = effective_billing_grants(organization=self.organization, user=outsider)
        self.assertEqual(grants.entitlements, [])
        self.assertEqual(grants.scope, [])
        self.assertEqual(grants.roles, [])

    def test_key_without_billing_scope_gets_role_but_no_entitlement(self):
        self._set_level(OWNER)
        grants = self._grants(_personal_key_authenticator(self.user, ["insight:read"]))
        self.assertEqual(grants.roles, ["owner"])
        self.assertEqual(grants.scope, [])
        self.assertEqual(grants.entitlements, [])

    def test_write_scope_and_star_imply_read(self):
        self._set_level(OWNER)
        for scopes in (["billing:write"], ["*"]):
            grants = self._grants(_personal_key_authenticator(self.user, scopes))
            self.assertEqual(grants.scope, ["billing:read", "billing:write"])
            self.assertEqual(grants.entitlements, [BillingEntitlement.FULL_ACCESS.value])

    def test_team_scoped_key_is_clipped_to_this_organizations_teams_whatever_the_role(self):
        self._set_level(OWNER)
        other_org = Organization.objects.create(name="other")
        foreign_team = Team.objects.create(organization=other_org, name="foreign")
        authenticator = _personal_key_authenticator(
            self.user, ["billing:read"], scoped_teams=[self.team.id, foreign_team.id]
        )
        grants = self._grants(authenticator)
        self.assertEqual(grants.projects, [self.team.id])
        self.assertEqual(grants.entitlements, [BillingEntitlement.FULL_ACCESS.value])

    def test_key_scoped_only_to_foreign_teams_grants_nothing(self):
        self._set_level(OWNER)
        other_org = Organization.objects.create(name="other")
        foreign_team = Team.objects.create(organization=other_org, name="foreign")
        grants = self._grants(_personal_key_authenticator(self.user, ["billing:read"], scoped_teams=[foreign_team.id]))
        self.assertEqual(grants.entitlements, [])

    def test_key_scoped_to_another_organization_grants_nothing(self):
        self._set_level(OWNER)
        other_org = Organization.objects.create(name="other")
        grants = self._grants(
            _personal_key_authenticator(self.user, ["billing:read"], scoped_organizations=[str(other_org.id)])
        )
        self.assertEqual(grants.entitlements, [])
        self.assertEqual(grants.roles, ["owner"])

    def test_what_a_member_can_see_is_not_in_the_token(self):
        # Visibility is a per-request filter on the series reads; the token carries only what a
        # credential is scoped to, so a member who sees one project of two still gets no list.
        self._set_level(MEMBER)
        self.member_read.return_value = True
        with patch("ee.billing.grants.visible_team_ids", return_value=[self.other_team.id]) as visible:
            grants = self._grants()
        self.assertEqual((grants.entitlements, grants.projects), ([BillingEntitlement.USAGE_READ.value], None))
        visible.assert_not_called()

    def test_project_secret_key_is_its_own_principal(self):
        grants = effective_billing_grants(
            organization=self.organization,
            authenticator=_project_secret_key_authenticator(self.team, ["billing:read"]),
        )
        self.assertTrue(grants.sub.startswith("project_key:"))
        self.assertEqual(grants.roles, [])
        self.assertEqual(grants.scope, ["billing:read"])
        self.assertEqual(grants.entitlements, [BillingEntitlement.USAGE_READ.value])
        self.assertEqual(grants.projects, [self.team.id])

    def test_project_secret_key_without_billing_scope_gets_nothing(self):
        grants = effective_billing_grants(
            organization=self.organization,
            authenticator=_project_secret_key_authenticator(self.team, ["feature_flag:read"]),
        )
        self.assertEqual(grants.entitlements, [])

    def test_project_secret_key_from_another_organization_gets_nothing(self):
        other_org = Organization.objects.create(name="other")
        foreign_team = Team.objects.create(organization=other_org, name="foreign")
        grants = effective_billing_grants(
            organization=self.organization,
            authenticator=_project_secret_key_authenticator(foreign_team, ["billing:read"]),
        )
        self.assertEqual(grants.entitlements, [])
