from types import SimpleNamespace
from typing import cast

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework.request import Request

from posthog.accessible_teams import AccessibleTeams, CredentialScopeDenied
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, PersonalAPIKey, Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

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

    def _request(self, *, credential_team_ids: list[int] | None) -> Request:
        authenticator: PersonalAPIKeyAuthentication | None = None
        if credential_team_ids is not None:
            authenticator = PersonalAPIKeyAuthentication()
            authenticator.personal_api_key = PersonalAPIKey.objects.create(
                user=self.user,
                label="scoped",
                secure_value=hash_key_value(generate_random_token_personal()),
                scopes=["*"],
                scoped_teams=credential_team_ids,
            )
        return cast(Request, SimpleNamespace(user=self.user, successful_authenticator=authenticator))

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

    def test_direct_construction_raises(self) -> None:
        with pytest.raises(TypeError):
            # nosemgrep: accessible-teams-built-directly -- this test proves that direct construction raises
            AccessibleTeams(user_id=self.user.pk, team_ids=(self.restricted_team.id,), _token=object())
