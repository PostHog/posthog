from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.models.file_system.starred_products import (
    DEFAULT_PRODUCT_PATHS,
    has_starred_product,
    star_default_products,
)
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_invite import OrganizationInvite
from posthog.products import Products

from products.access_control.backend.models.access_control import AccessControl


class TestDefaultStarredProducts(BaseTest):
    def _default_paths_for(self, user: User, team: Team) -> set[str]:
        return set(FileSystemShortcut.objects.filter(user=user, team=team).values_list("path", flat=True))

    def test_default_product_paths_are_valid_products(self):
        assert set(DEFAULT_PRODUCT_PATHS) <= set(Products.get_product_paths())

    @parameterized.expand([("same_environment", False), ("other_environment_of_the_project", True)])
    def test_leaves_a_user_who_already_starred_products_in_the_project_alone(
        self, _name: str, star_in_other_environment: bool
    ) -> None:
        user = User.objects.create_user(email="starred@posthog.com", password="password", first_name="Starred")
        other_environment = Team.objects.create(organization=self.organization, project=self.project, name="Staging")
        starred_team = other_environment if star_in_other_environment else self.team
        FileSystemShortcut.objects.create(team=starred_team, user=user, path="Logs", type="logs")

        star_default_products(user, self.team)

        starred = list(
            FileSystemShortcut.objects.filter(user=user, team__project_id=self.project.id).values_list(
                "path", flat=True
            )
        )
        assert starred == ["Logs"]

    @parameterized.expand(
        [
            ("a star in this environment", "same", None, True),
            ("a star in another environment of the project", "other", None, True),
            ("a starred file with the same name", "same", "42", False),
        ]
    )
    def test_has_starred_product(self, _name: str, environment: str, ref: str | None, expected: bool) -> None:
        other_environment = Team.objects.create(organization=self.organization, project=self.project, name="Staging")
        team = other_environment if environment == "other" else self.team
        user = User.objects.create_user(email="stars@posthog.com", password="password", first_name="Stars")
        FileSystemShortcut.objects.create(team=team, user=user, path="Error tracking", type="error_tracking", ref=ref)

        assert has_starred_product(user, self.team, ["Error tracking", "Session replay"]) is expected
        assert has_starred_product(user, self.team, ["Session replay"]) is False

    def _make_team_private(self, team: Team) -> None:
        # Project-level access controls only apply when the org has the feature.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        AccessControl.objects.create(team=team, resource="project", resource_id=str(team.id), access_level="none")

    def test_accepting_invite_adds_default_products_for_private_project_access(self):
        # Mark the team private, so seeding can only come from the invite's access grant,
        # not from the org-wide seeding in User.join.
        self._make_team_private(self.team)
        new_user = User.objects.create_user(email="newuser@posthog.com", password="password", first_name="New")

        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="newuser@posthog.com",
            private_project_access=[{"id": self.team.id, "level": "member"}],
        )
        invite.use(new_user, prevalidated=True)

        assert self._default_paths_for(new_user, self.team) == set(DEFAULT_PRODUCT_PATHS)

    def test_accepting_invite_without_private_project_access_adds_default_products(self):
        new_user = User.objects.create_user(email="newuser@posthog.com", password="password", first_name="New")

        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="newuser@posthog.com",
            private_project_access=None,
        )
        invite.use(new_user, prevalidated=True)

        assert self._default_paths_for(new_user, self.team) == set(DEFAULT_PRODUCT_PATHS)

    @parameterized.expand([("new_project", False), ("new_environment_of_an_existing_project", True)])
    def test_creating_team_adds_default_products_only_for_a_new_project(
        self, _name: str, in_existing_project: bool
    ) -> None:
        member = User.objects.create_user(email="member@posthog.com", password="password", first_name="Member")
        member.join(organization=self.organization)
        creator = User.objects.create_user(email="creator@posthog.com", password="password", first_name="Creator")
        creator.join(organization=self.organization)
        # Both users removed every star, which the new environment must not undo.
        FileSystemShortcut.objects.filter(user__in=[member, creator]).delete()

        new_team = Team.objects.create_with_data(
            initiating_user=creator,
            organization=self.organization,
            name="New Team",
            **({"project": self.project} if in_existing_project else {}),
        )

        expected = set() if in_existing_project else set(DEFAULT_PRODUCT_PATHS)
        assert self._default_paths_for(creator, new_team) == expected
        assert self._default_paths_for(member, new_team) == expected

    def test_creating_team_in_a_large_organization_adds_default_products_after_commit(self) -> None:
        with (
            patch("posthog.models.team.team.ASYNC_DEFAULT_STARRED_PRODUCTS_THRESHOLD", 0),
            self.captureOnCommitCallbacks(execute=True),
        ):
            new_team = Team.objects.create_with_data(
                initiating_user=self.user, organization=self.organization, name="New Team"
            )
            assert self._default_paths_for(self.user, new_team) == set()

        assert self._default_paths_for(self.user, new_team) == set(DEFAULT_PRODUCT_PATHS)

    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_access_control_signal_adds_default_products(self):
        # Private team: joining the org must NOT seed it; the explicit access grant must.
        self._make_team_private(self.team)
        user = User.objects.create_user(email="signal@posthog.com", password="password", first_name="Signal")
        user.join(organization=self.organization)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=user)

        assert self._default_paths_for(user, self.team) == set()

        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=membership,
            access_level="member",
        )

        assert self._default_paths_for(user, self.team) == set(DEFAULT_PRODUCT_PATHS)
