from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import param, parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.personal_api_key import (
    PersonalAPIKey,
    get_organization_ids_in_key_scope,
    get_organization_personal_api_keys,
)
from posthog.models.utils import generate_random_token_personal, hash_key_value

THIS_ORG = "this_org"
OTHER_ORG = "other_org"
THIS_TEAM = "this_team"
OTHER_TEAM = "other_team"


class TestGetOrganizationPersonalAPIKeys(BaseTest):
    def setUp(self):
        super().setUp()
        self.member = User.objects.create_and_join(self.organization, "member@x.com", None)
        self.other_org = Organization.objects.create(name="other")
        self.other_team = Team.objects.create(organization=self.other_org, name="other team")

    def _create_key(self, user=None, label="key", scopes=("insight:read",), **fields):
        return PersonalAPIKey.objects.create(
            user=user or self.member,
            label=label,
            secure_value=hash_key_value(generate_random_token_personal()),
            scopes=list(scopes),
            **fields,
        )

    def _listed_ids(self):
        return set(get_organization_personal_api_keys(self.organization).values_list("id", flat=True))

    @parameterized.expand(
        [
            ("unscoped_null", None, None, True),
            ("unscoped_empty_lists", [], [], True),
            ("this_org", [THIS_ORG], None, True),
            ("this_org_empty_teams", [THIS_ORG], [], True),
            ("this_team", None, [THIS_TEAM], True),
            ("empty_orgs_this_team", [], [THIS_TEAM], True),
            ("this_org_and_this_team", [THIS_ORG], [THIS_TEAM], True),
            ("both_orgs_both_teams", [THIS_ORG, OTHER_ORG], [THIS_TEAM, OTHER_TEAM], True),
            ("other_org", [OTHER_ORG], None, False),
            ("other_team", None, [OTHER_TEAM], False),
            ("other_org_this_team", [OTHER_ORG], [THIS_TEAM], False),
            ("both_orgs_other_team", [THIS_ORG, OTHER_ORG], [OTHER_TEAM], False),
        ]
    )
    def test_scope_lists_decide_listing(self, _name, scoped_organizations, scoped_teams, expected_listed):
        ids = {
            THIS_ORG: str(self.organization.id),
            OTHER_ORG: str(self.other_org.id),
            THIS_TEAM: self.team.id,
            OTHER_TEAM: self.other_team.id,
        }
        key = self._create_key(
            scoped_organizations=None if scoped_organizations is None else [ids[org] for org in scoped_organizations],
            scoped_teams=None if scoped_teams is None else [ids[team] for team in scoped_teams],
        )
        organization_ids_in_scope = get_organization_ids_in_key_scope(
            key, {self.team.id: str(self.organization.id), self.other_team.id: str(self.other_org.id)}
        )

        assert (key.id in self._listed_ids()) == expected_listed
        assert (
            organization_ids_in_scope is None or str(self.organization.id) in organization_ids_in_scope
        ) == expected_listed

    @parameterized.expand(
        [
            param("expired", expires_in=timedelta(minutes=-1), expected_listed=False),
            param("not_yet_expired", expires_in=timedelta(days=1), expected_listed=True),
            param("no_scopes", scopes=(), expected_listed=False),
            param("inactive_owner", owner_is_active=False, expected_listed=False),
            param("member_key_blocked_by_org", members_can_use_keys=False, expected_listed=False),
            param(
                "member_key_blocked_by_org_owner_admin_elsewhere",
                members_can_use_keys=False,
                admin_elsewhere=True,
                expected_listed=False,
            ),
            param(
                "admin_key_when_org_blocks_member_keys",
                members_can_use_keys=False,
                level=OrganizationMembership.Level.ADMIN,
                expected_listed=True,
            ),
            param(
                "member_key_when_org_lacks_security_settings",
                members_can_use_keys=False,
                has_security_settings=False,
                expected_listed=True,
            ),
        ]
    )
    def test_lists_only_keys_that_can_authenticate(
        self,
        _name,
        expected_listed,
        scopes=("insight:read",),
        expires_in=None,
        owner_is_active=True,
        members_can_use_keys=True,
        has_security_settings=True,
        level=OrganizationMembership.Level.MEMBER,
        admin_elsewhere=False,
    ):
        self.organization.available_product_features = (
            [{"key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS, "name": "organization_security_settings"}]
            if has_security_settings
            else []
        )
        self.organization.members_can_use_personal_api_keys = members_can_use_keys
        self.organization.save()
        OrganizationMembership.objects.filter(user=self.member, organization=self.organization).update(level=level)
        if admin_elsewhere:
            self.member.join(organization=self.other_org, level=OrganizationMembership.Level.ADMIN)
        self.member.is_active = owner_is_active
        self.member.save()
        with time_machine.travel("2026-11-01T00:00:00Z", tick=False):
            key = self._create_key(
                scopes=scopes, expires_at=timezone.now() + expires_in if expires_in is not None else None
            )

            assert (key.id in self._listed_ids()) == expected_listed

    def test_excludes_keys_of_non_members(self):
        outsider = User.objects.create(email="outsider@x.com")
        self._create_key(outsider, label="outsider-unscoped")

        assert get_organization_personal_api_keys(self.organization).count() == 0

    def test_deduplicates(self):
        self._create_key(
            scoped_organizations=[str(self.organization.id)],
            scoped_teams=[self.team.id],
            label="both",
        )

        assert get_organization_personal_api_keys(self.organization).count() == 1
