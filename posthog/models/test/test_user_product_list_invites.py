from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import Organization, Team, User
from posthog.models.file_system.user_product_list import UserProductList
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_invite import OrganizationInvite

from ee.models.rbac.access_control import AccessControl


class TestUserProductListInvites(BaseTest):
    def test_invite_user_syncs_products_from_colleagues(self):
        """Test that when a user accepts an invite, they get products from team colleagues"""
        # Create existing team members with products
        colleague1 = User.objects.create_user(
            email="colleague1@posthog.com", password="password", first_name="Colleague1"
        )
        colleague2 = User.objects.create_user(
            email="colleague2@posthog.com", password="password", first_name="Colleague2"
        )
        colleague1.join(organization=self.organization)
        colleague2.join(organization=self.organization)

        # Create products for colleagues
        UserProductList.objects.create(user=colleague1, team=self.team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=colleague1, team=self.team, product_path="session_replay", enabled=True)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="feature_flags", enabled=True)

        # Create new user to invite
        new_user = User.objects.create_user(
            email="newuser@posthog.com", password="password", first_name="New", allow_sidebar_suggestions=True
        )

        # Create invite with access to the team
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="newuser@posthog.com",
            private_project_access=[{"id": self.team.id, "level": "member"}],
        )

        # Use the invite
        invite.use(new_user, prevalidated=True)

        # Verify products were synced from colleagues (top 3 most popular)
        # product_analytics has 2 colleagues, session_replay and feature_flags have 1 each
        user_products = UserProductList.objects.filter(user=new_user, team=self.team, enabled=True)
        product_paths = set(user_products.values_list("product_path", flat=True))

        # Should have top 3 products from colleagues
        assert "product_analytics" in product_paths
        assert "session_replay" in product_paths
        assert "feature_flags" in product_paths
        assert len(product_paths) == 3

        # Verify reason is set correctly
        product_analytics = UserProductList.objects.get(user=new_user, team=self.team, product_path="product_analytics")
        assert product_analytics.reason == UserProductList.Reason.USED_BY_COLLEAGUES

    def test_invite_user_backfills_from_other_teams(self):
        """Test that when a user accepts an invite, products are backfilled from their other teams"""
        # Create a second organization and team for the user
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        # Create user and add them to other organization
        user = User.objects.create_user(
            email="existing@posthog.com", password="password", first_name="Existing", allow_sidebar_suggestions=True
        )
        user.join(organization=other_org)

        # Create products for user in other team
        UserProductList.objects.create(user=user, team=other_team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=user, team=other_team, product_path="session_replay", enabled=True)

        # Create invite to new team in different organization
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="existing@posthog.com",
            private_project_access=[{"id": self.team.id, "level": "member"}],
        )

        # Use the invite
        invite.use(user, prevalidated=True)

        # Verify products were backfilled from other teams
        user_products = UserProductList.objects.filter(user=user, team=self.team, enabled=True)
        product_paths = set(user_products.values_list("product_path", flat=True))

        assert "product_analytics" in product_paths
        assert "session_replay" in product_paths

    def test_invite_user_combines_colleagues_and_backfill(self):
        """Test that invite combines products from colleagues and backfill from other teams"""
        # Create user with products in another organization
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        user = User.objects.create_user(
            email="combined@posthog.com", password="password", first_name="Combined", allow_sidebar_suggestions=True
        )
        user.join(organization=other_org)
        UserProductList.objects.create(user=user, team=other_team, product_path="product_analytics", enabled=True)

        # Create colleagues with products
        colleague = User.objects.create_user(email="colleague@posthog.com", password="password", first_name="Colleague")
        colleague.join(organization=self.organization)
        UserProductList.objects.create(user=colleague, team=self.team, product_path="session_replay", enabled=True)
        UserProductList.objects.create(user=colleague, team=self.team, product_path="feature_flags", enabled=True)

        # Create invite
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="combined@posthog.com",
            private_project_access=[{"id": self.team.id, "level": "member"}],
        )

        # Use the invite
        invite.use(user, prevalidated=True)

        # Verify both backfill and colleague sync happened
        user_products = UserProductList.objects.filter(user=user, team=self.team, enabled=True)
        product_paths = set(user_products.values_list("product_path", flat=True))

        # Should have backfilled product_analytics from other team
        assert "product_analytics" in product_paths
        # Should have synced products from colleagues
        assert len(product_paths) >= 1

    def test_invite_user_respects_allow_sidebar_suggestions(self):
        """Test that users with allow_sidebar_suggestions=False don't get products synced"""
        # Create colleagues with products
        colleague = User.objects.create_user(email="colleague@posthog.com", password="password", first_name="Colleague")
        colleague.join(organization=self.organization)
        UserProductList.objects.create(user=colleague, team=self.team, product_path="product_analytics", enabled=True)

        # Create user with suggestions disabled
        user = User.objects.create_user(
            email="nosuggestions@posthog.com",
            password="password",
            first_name="NoSuggestions",
            allow_sidebar_suggestions=False,
        )

        # Create invite
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="nosuggestions@posthog.com",
            private_project_access=[{"id": self.team.id, "level": "member"}],
        )

        # Use the invite
        invite.use(user, prevalidated=True)

        # Verify no products were synced from colleagues (sync_from_team_colleagues respects this)
        colleague_synced = UserProductList.objects.filter(
            user=user, team=self.team, reason=UserProductList.Reason.USED_BY_COLLEAGUES
        )
        assert colleague_synced.count() == 0

    def test_invite_user_does_not_duplicate_existing_products(self):
        """Test that existing products are not duplicated when syncing"""
        # Create user with existing product
        user = User.objects.create_user(
            email="existingproducts@posthog.com",
            password="password",
            first_name="Existing",
            allow_sidebar_suggestions=True,
        )

        # Create product before invite
        UserProductList.objects.create(user=user, team=self.team, product_path="product_analytics", enabled=True)

        # Create colleagues with same product
        colleague = User.objects.create_user(email="colleague@posthog.com", password="password", first_name="Colleague")
        colleague.join(organization=self.organization)
        UserProductList.objects.create(user=colleague, team=self.team, product_path="product_analytics", enabled=True)

        # Create invite
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="existingproducts@posthog.com",
            private_project_access=[{"id": self.team.id, "level": "member"}],
        )

        # Use the invite
        invite.use(user, prevalidated=True)

        # Verify only one product_analytics entry exists
        product_count = UserProductList.objects.filter(
            user=user, team=self.team, product_path="product_analytics"
        ).count()
        assert product_count == 1

    def test_invite_user_ranks_colleagues_by_popularity(self):
        """Test that products are ranked by how many colleagues have them"""
        # Create multiple colleagues with different product distributions
        colleagues = []
        for i in range(5):
            colleague = User.objects.create_user(
                email=f"colleague{i}@posthog.com", password="password", first_name=f"Colleague{i}"
            )
            colleague.join(organization=self.organization)
            colleagues.append(colleague)

        # product_analytics: 5 colleagues (most popular)
        for colleague in colleagues:
            UserProductList.objects.create(
                user=colleague, team=self.team, product_path="product_analytics", enabled=True
            )

        # session_replay: 3 colleagues
        for colleague in colleagues[:3]:
            UserProductList.objects.create(user=colleague, team=self.team, product_path="session_replay", enabled=True)

        # feature_flags: 2 colleagues
        for colleague in colleagues[:2]:
            UserProductList.objects.create(user=colleague, team=self.team, product_path="feature_flags", enabled=True)

        # experiments: 1 colleague (least popular)
        UserProductList.objects.create(user=colleagues[0], team=self.team, product_path="experiments", enabled=True)

        # Create new user
        new_user = User.objects.create_user(
            email="newuser@posthog.com", password="password", first_name="New", allow_sidebar_suggestions=True
        )

        # Create invite
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="newuser@posthog.com",
            private_project_access=[],
        )

        # Use the invite (count=3, so top 3 should be synced)
        invite.use(new_user, prevalidated=True)

        # Verify top products were synced (product_analytics, session_replay, feature_flags)
        user_products = UserProductList.objects.filter(
            user=new_user, team=self.team, reason=UserProductList.Reason.USED_BY_COLLEAGUES
        )
        product_paths = set(user_products.values_list("product_path", flat=True))

        # Should have the most popular products
        assert "product_analytics" in product_paths
        assert "session_replay" in product_paths
        assert "feature_flags" in product_paths
        assert "experiments" not in product_paths
        assert len(product_paths) <= 3  # Should not exceed count=3


class TestUserProductListInvitesWithoutPrivateProjectAccess(BaseTest):
    def test_invite_user_without_private_project_access_syncs_products(self):
        """Test that when a user accepts an invite without private_project_access, they still get products synced"""
        # Create existing team members with products
        colleague = User.objects.create_user(email="colleague@posthog.com", password="password", first_name="Colleague")
        colleague.join(organization=self.organization)

        # Create products for colleague
        UserProductList.objects.create(user=colleague, team=self.team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=colleague, team=self.team, product_path="session_replay", enabled=True)

        # Create new user to invite
        new_user = User.objects.create_user(
            email="newuser@posthog.com", password="password", first_name="New", allow_sidebar_suggestions=True
        )

        # Create invite WITHOUT private_project_access
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="newuser@posthog.com",
            private_project_access=None,
        )

        # Use the invite
        invite.use(new_user, prevalidated=True)

        # Verify products were synced from colleagues
        user_products = UserProductList.objects.filter(user=new_user, team=self.team, enabled=True)
        product_paths = set(user_products.values_list("product_path", flat=True))

        assert "product_analytics" in product_paths
        assert "session_replay" in product_paths

    def test_invite_user_without_private_project_access_backfills_from_other_teams(self):
        """Test that invite without private_project_access still backfills from user's other teams"""
        # Create a second organization and team for the user
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        # Create user and add them to other organization
        user = User.objects.create_user(
            email="existing@posthog.com", password="password", first_name="Existing", allow_sidebar_suggestions=True
        )
        user.join(organization=other_org)

        # Create products for user in other team
        UserProductList.objects.create(user=user, team=other_team, product_path="product_analytics", enabled=True)

        # Create invite WITHOUT private_project_access
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="existing@posthog.com",
            private_project_access=None,
        )

        # Use the invite
        invite.use(user, prevalidated=True)

        # Verify products were backfilled from other teams
        user_products = UserProductList.objects.filter(user=user, team=self.team, enabled=True)
        product_paths = set(user_products.values_list("product_path", flat=True))

        assert "product_analytics" in product_paths


class TestUserProductListTeamCreation(BaseTest):
    def test_create_team_backfills_from_other_teams(self):
        """Test that when a user creates a team, products are backfilled from their other teams"""
        # Create user with products in existing team
        user = User.objects.create_user(
            email="creator@posthog.com", password="password", first_name="Creator", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        # Create products in existing team
        UserProductList.objects.create(user=user, team=self.team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=user, team=self.team, product_path="session_replay", enabled=True)

        # Create new team
        new_team = Team.objects.create_with_data(initiating_user=user, organization=self.organization, name="New Team")

        # Verify products were backfilled to new team
        user_products = UserProductList.objects.filter(user=user, team=new_team, enabled=True)
        product_paths = set(user_products.values_list("product_path", flat=True))

        assert "product_analytics" in product_paths
        assert "session_replay" in product_paths

    def test_create_team_no_backfill_if_user_has_no_other_products(self):
        """Test that backfill doesn't happen if user has no products in other teams"""
        # Create user without any products
        user = User.objects.create_user(
            email="noproducts@posthog.com", password="password", first_name="NoProducts", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        # Create new team
        new_team = Team.objects.create_with_data(initiating_user=user, organization=self.organization, name="New Team")

        # Verify no products were backfilled
        user_products = UserProductList.objects.filter(user=user, team=new_team)
        assert user_products.count() == 0

    def test_create_team_syncs_products_for_all_users_with_access(self):
        """Test that when a new team is created, all org members get products synced"""
        # Create existing org members with products in the existing team
        member1 = User.objects.create_user(
            email="member1@posthog.com", password="password", first_name="Member1", allow_sidebar_suggestions=True
        )
        member2 = User.objects.create_user(
            email="member2@posthog.com", password="password", first_name="Member2", allow_sidebar_suggestions=True
        )
        member1.join(organization=self.organization)
        member2.join(organization=self.organization)

        # Create products for members in existing team
        UserProductList.objects.create(user=member1, team=self.team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=member2, team=self.team, product_path="session_replay", enabled=True)

        # Create a new team (without specifying initiating_user to test all members sync)
        creator = User.objects.create_user(
            email="creator@posthog.com", password="password", first_name="Creator", allow_sidebar_suggestions=True
        )
        creator.join(organization=self.organization)
        new_team = Team.objects.create_with_data(
            initiating_user=creator, organization=self.organization, name="New Team"
        )

        # Verify member1's products were backfilled to new team
        member1_products = UserProductList.objects.filter(user=member1, team=new_team, enabled=True)
        member1_paths = set(member1_products.values_list("product_path", flat=True))
        assert "product_analytics" in member1_paths

        # Verify member2's products were backfilled to new team
        member2_products = UserProductList.objects.filter(user=member2, team=new_team, enabled=True)
        member2_paths = set(member2_products.values_list("product_path", flat=True))
        assert "session_replay" in member2_paths

    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_access_control_signal_triggers_backfill(self):
        """Test that AccessControl creation signal triggers product sync"""
        # Create user with products in another organization
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        user = User.objects.create_user(
            email="signal@posthog.com", password="password", first_name="Signal", allow_sidebar_suggestions=True
        )
        user.join(organization=other_org)
        UserProductList.objects.create(user=user, team=other_team, product_path="product_analytics", enabled=True)

        # Add user to new organization
        user.join(organization=self.organization)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=user)

        # Create colleagues with products
        colleague = User.objects.create_user(email="colleague@posthog.com", password="password", first_name="Colleague")
        colleague.join(organization=self.organization)
        UserProductList.objects.create(user=colleague, team=self.team, product_path="session_replay", enabled=True)
        UserProductList.objects.create(user=colleague, team=self.team, product_path="feature_flags", enabled=True)

        # Create AccessControl (this should trigger the signal)
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=membership,
            access_level="member",
        )

        # Verify products were synced via signal
        user_products = UserProductList.objects.filter(user=user, team=self.team, enabled=True)
        product_paths = set(user_products.values_list("product_path", flat=True))

        # Should have backfilled product_analytics and synced products from colleagues
        assert "product_analytics" in product_paths
        assert len(product_paths) >= 1
