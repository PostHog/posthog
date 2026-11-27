from uuid import uuid4

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, User

from products.access_control.backend.facade.api import (
    likely_role,
    likely_roles,
    list_external_role_references,
    valid_role_member_user_ids_by_role,
)
from products.access_control.backend.facade.contracts import RoleMatchSource
from products.access_control.backend.likely_role import ExternalReferenceCandidate, RoleCandidate, RoleMatcher
from products.access_control.backend.models.role import Role, RoleMembership
from products.access_control.backend.models.role_external_reference import RoleExternalReference


class TestRoleMatcherPure(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.replay_id = uuid4()
        self.analytics_id = uuid4()
        self.product_analytics_id = uuid4()
        self.devex_id = uuid4()
        self.growth_id = uuid4()
        self.engineering_id = uuid4()
        self.flags_id = uuid4()
        self.error_tracking_id = uuid4()

        self.roles = [
            RoleCandidate(id=self.replay_id, name="Replay"),
            RoleCandidate(id=self.analytics_id, name="Analytics"),
            RoleCandidate(id=self.product_analytics_id, name="Product Analytics"),
            RoleCandidate(id=self.devex_id, name="Dev Ex"),
            RoleCandidate(id=self.growth_id, name="Growth"),
            RoleCandidate(id=self.engineering_id, name="Engineering"),
            RoleCandidate(id=self.flags_id, name="Feature Flag"),
            RoleCandidate(id=self.error_tracking_id, name="Error Tracking"),
        ]

    @parameterized.expand(
        [
            ("exact_slug", "@posthog/product-analytics", "Product Analytics", RoleMatchSource.NAME_MATCH),
            ("team_prefix", "@PostHog/team-replay", "Replay", RoleMatchSource.NAME_MATCH),
            ("team_suffix", "replay-team", "Replay", RoleMatchSource.NAME_MATCH),
            ("compact_tokens", "@posthog/team-devex", "Dev Ex", RoleMatchSource.NAME_MATCH),
            ("domain_eng_suffix", "@posthog/growth-eng", "Growth", RoleMatchSource.NAME_MATCH),
            ("engineering_itself", "@posthog/team-engineering", "Engineering", RoleMatchSource.NAME_MATCH),
            ("plural_to_singular", "@posthog/feature-flags", "Feature Flag", RoleMatchSource.NAME_MATCH),
        ]
    )
    def test_heuristic_name_matching(
        self,
        _name: str,
        team_name: str,
        expected_role_name: str,
        expected_source: RoleMatchSource,
    ) -> None:
        matcher = RoleMatcher(references=[], roles=self.roles)
        matched = matcher.match(team_name)
        assert matched is not None
        assert matched.name == expected_role_name
        assert matched.source == expected_source

    @parameterized.expand(
        [
            ("generic_substring_rejected", "@posthog/web-analytics"),
            ("email_rejected", "owner@example.com"),
            ("unowned_rejected", "unowned"),
            ("empty_rejected", "   "),
            ("bare_at_rejected", "@"),
            ("nested_slash_rejected", "@org/sub/team"),
        ]
    )
    def test_rejects_non_teams_and_weak_matches(self, _name: str, team_name: str) -> None:
        matcher = RoleMatcher(references=[], roles=self.roles)
        assert matcher.match(team_name) is None

    def test_explicit_reference_overrides_name_match_for_matching_provider_org(self) -> None:
        references = [
            ExternalReferenceCandidate(
                provider_organization_id="posthog",
                provider_role_id="team-replay",
                provider_role_slug="team-replay",
                role_id=self.error_tracking_id,
                role_name="Error Tracking",
            )
        ]
        matcher = RoleMatcher(references=references, roles=self.roles)

        posthog_match = matcher.match("@PostHog/team-replay")
        assert posthog_match is not None
        assert posthog_match.id == self.error_tracking_id
        assert posthog_match.source == RoleMatchSource.EXTERNAL_REFERENCE

        other_org_match = matcher.match("@OtherOrg/team-replay")
        assert other_org_match is not None
        assert other_org_match.id == self.replay_id
        assert other_org_match.source == RoleMatchSource.NAME_MATCH

    def test_conflicting_bare_slug_across_provider_orgs_returns_none(self) -> None:
        references = [
            ExternalReferenceCandidate(
                provider_organization_id="org-one",
                provider_role_id="shared-team",
                provider_role_slug="shared-team",
                role_id=self.replay_id,
                role_name="Replay",
            ),
            ExternalReferenceCandidate(
                provider_organization_id="org-two",
                provider_role_id="shared-team",
                provider_role_slug="shared-team",
                role_id=self.growth_id,
                role_name="Growth",
            ),
        ]
        matcher = RoleMatcher(references=references, roles=self.roles)

        assert matcher.match("shared-team") is None
        disambiguated = matcher.match("shared-team", default_organization="org-two")
        assert disambiguated is not None
        assert disambiguated.id == self.growth_id

    def test_tied_fuzzy_candidates_return_none(self) -> None:
        matcher = RoleMatcher(
            references=[],
            roles=[
                RoleCandidate(id=uuid4(), name="Platform A"),
                RoleCandidate(id=uuid4(), name="Platform B"),
            ],
        )
        assert matcher.match("@posthog/platform-c") is None


class TestLikelyRoleFacade(BaseTest):
    def test_resolves_explicit_and_heuristic_roles_isolated_to_organization(self) -> None:
        replay_role = Role.objects.create(name="Replay", organization=self.organization)
        cymbal_role = Role.objects.create(name="Error Tracking", organization=self.organization)
        RoleExternalReference.objects.create(
            organization=self.organization,
            role=cymbal_role,
            provider="github",
            provider_organization_id="posthog",
            provider_role_id="team-cymbal",
            provider_role_slug="team-cymbal",
            provider_role_name="@posthog/team-cymbal",
            created_by=self.user,
        )

        other_org = Organization.objects.create(name="Other Org")
        foreign_role = Role.objects.create(name="Secret Team", organization=other_org)
        RoleExternalReference.objects.create(
            organization=other_org,
            role=foreign_role,
            provider="github",
            provider_organization_id="posthog",
            provider_role_id="team-secret",
            provider_role_slug="team-secret",
            provider_role_name="@posthog/team-secret",
        )

        explicit = likely_role("@posthog/team-cymbal", team_id=self.team.id)
        assert explicit is not None
        assert explicit.id == cymbal_role.id
        assert explicit.source == RoleMatchSource.EXTERNAL_REFERENCE

        batch = likely_roles(
            ["@posthog/team-cymbal", "@posthog/team-replay", "@posthog/team-secret"],
            organization_id=self.organization.id,
        )
        assert set(batch.keys()) == {"@posthog/team-cymbal", "@posthog/team-replay"}
        assert batch["@posthog/team-replay"].id == replay_role.id
        assert batch["@posthog/team-replay"].source == RoleMatchSource.NAME_MATCH

        refs = list_external_role_references(organization_id=self.organization.id)
        assert [ref.role_id for ref in refs] == [cymbal_role.id]

    def test_valid_role_member_user_ids_by_role_excludes_mismatched_org_membership(self) -> None:
        role = Role.objects.create(name="Replay", organization=self.organization)
        RoleMembership.objects.create(
            role=role,
            user=self.user,
            organization_member=self.organization_membership,
        )
        other_org = Organization.objects.create(name="Other Org")
        outsider = User.objects.create(email="outsider@example.com")
        outsider_membership = OrganizationMembership.objects.create(organization=other_org, user=outsider)
        RoleMembership.objects.create(role=role, user=outsider, organization_member=outsider_membership)

        by_role = valid_role_member_user_ids_by_role(role_ids=[role.id])
        assert by_role == {role.id: frozenset({self.user.id})}
