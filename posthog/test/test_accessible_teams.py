from types import SimpleNamespace
from typing import cast

import pytest
from posthog.test.base import BaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.accessible_teams import AccessibleTeams, CredentialScopeDenied
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team
from posthog.models.organization_ip_restrictions import OrganizationIPRestrictions
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.session.backend import SessionStore

from products.access_control.backend.models.access_control import AccessControl


class TestAccessibleTeams(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.open_team = Team.objects.create(organization=self.organization, name="Open Team")
        self.restricted_team = Team.objects.create(organization=self.organization, name="Restricted Team")
        AccessControl.objects.create(
            team=self.restricted_team,
            resource="project",
            resource_id=str(self.restricted_team.id),
            access_level="none",
        )

    def _request(
        self,
        *,
        ip: str = "127.0.0.1",
        credential_team_ids: list[int] | None = None,
        credential_organization_ids: list[str] | None = None,
    ) -> Request:
        authenticator: PersonalAPIKeyAuthentication | None = None
        if credential_team_ids is not None or credential_organization_ids is not None:
            authenticator = PersonalAPIKeyAuthentication()
            authenticator.personal_api_key = PersonalAPIKey.objects.create(
                user=self.user,
                label="scoped",
                secure_value=hash_key_value(generate_random_token_personal()),
                scopes=["*"],
                scoped_teams=credential_team_ids or [],
                scoped_organizations=credential_organization_ids or [],
            )
        raw = APIRequestFactory().post("/api/oauth/device/approve/", REMOTE_ADDR=ip)
        raw.session = SessionStore()
        return cast(Request, SimpleNamespace(user=self.user, successful_authenticator=authenticator, _request=raw))

    @parameterized.expand(
        [
            ("accessible_team", "open", None, True),
            ("restricted_team", "restricted", None, False),
            ("missing_team", "missing", None, False),
            ("team_inside_credential", "open", "open", True),
            ("team_outside_credential", "open", "self_team", False),
            ("all_teams_from_session", "all", None, True),
            ("all_teams_from_confined_credential", "all", "self_team", False),
        ]
    )
    def test_for_request_grants_only_teams_that_user_and_credential_reach(
        self, _name: str, requested: str, credential: str | None, allowed: bool
    ) -> None:
        team_ids_by_name = {
            "open": [self.open_team.id],
            "restricted": [self.restricted_team.id],
            "missing": [self.restricted_team.id + 10_000],
            "self_team": [self.team.id],
        }
        requested_team_ids = None if requested == "all" else team_ids_by_name[requested]
        request = self._request(credential_team_ids=team_ids_by_name[credential] if credential else None)

        if allowed:
            teams = AccessibleTeams.for_request(request, requested_team_ids)
            self.assertEqual(teams.user_id, self.user.pk)
            self.assertEqual(teams.team_ids, tuple(requested_team_ids) if requested_team_ids else None)
        else:
            with pytest.raises(CredentialScopeDenied):
                AccessibleTeams.for_request(request, requested_team_ids)

    @parameterized.expand(
        [
            (confined, ip, allowed)
            for confined in (False, True)
            for ip, allowed in (("203.0.113.7", True), ("198.51.100.7", False))
        ]
    )
    def test_for_request_applies_the_requested_teams_ip_policy(self, confined: bool, ip: str, allowed: bool) -> None:
        other, _, other_team = Organization.objects.bootstrap(self.user)
        self.user.current_organization = other
        self.user.current_team = other_team
        self.user.save(update_fields=["current_organization", "current_team"])
        with self.captureOnCommitCallbacks(execute=True):
            OrganizationIPRestrictions.objects.create(
                organization=self.organization, ip_restrictions=["203.0.113.0/24"]
            )
        request = self._request(ip=ip, credential_team_ids=[self.open_team.id] if confined else None)
        if allowed:
            self.assertEqual(AccessibleTeams.for_request(request, [self.open_team.id]).team_ids, (self.open_team.id,))
        else:
            with pytest.raises(PermissionDenied, match="IP address"):
                AccessibleTeams.for_request(request, [self.open_team.id])

    def test_for_request_denies_team_outside_credential_scoped_organizations(self) -> None:
        other_organization = Organization.objects.create(name="Other")
        OrganizationMembership.objects.create(
            user=self.user, organization=other_organization, level=OrganizationMembership.Level.MEMBER
        )
        other_team = Team.objects.create(organization=other_organization, name="Other Open Team")
        request = self._request(credential_organization_ids=[str(self.organization.id)])
        with pytest.raises(CredentialScopeDenied):
            AccessibleTeams.for_request(request, [other_team.id])

    def test_for_request_allows_team_inside_credential_scoped_organizations(self) -> None:
        request = self._request(credential_organization_ids=[str(self.organization.id)])
        teams = AccessibleTeams.for_request(request, [self.open_team.id])
        self.assertEqual(teams.team_ids, (self.open_team.id,))

    def test_for_request_denies_all_teams_from_org_confined_credential(self) -> None:
        request = self._request(credential_organization_ids=[str(self.organization.id)])
        with pytest.raises(CredentialScopeDenied):
            AccessibleTeams.for_request(request, None)

    def test_for_user_queries_do_not_grow_with_the_team_count(self) -> None:
        more_team_ids = [Team.objects.create(organization=self.organization, name=f"Team {i}").id for i in range(3)]
        AccessibleTeams.for_user(self.user, [self.team.id])

        with CaptureQueriesContext(connection) as two_teams:
            AccessibleTeams.for_user(self.user, [self.team.id, self.open_team.id])
        with CaptureQueriesContext(connection) as five_teams:
            AccessibleTeams.for_user(self.user, [self.team.id, self.open_team.id, *more_team_ids])

        assert len(five_teams.captured_queries) == len(two_teams.captured_queries)

    def test_direct_construction_raises(self) -> None:
        with pytest.raises(TypeError):
            # nosemgrep: accessible-teams-built-directly -- this test proves that direct construction raises
            AccessibleTeams(user_id=self.user.pk, team_ids=(self.restricted_team.id,), _token=object())
