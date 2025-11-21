from posthog.test.base import BaseTest

from posthog.models import User
from posthog.models.file_system.user_product_list import UserProductList, get_user_product_list_count


class TestUserProductList(BaseTest):
    def test_sync_filters_out_existing_products_with_precomputed_counts(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        UserProductList.objects.create(user=user, team=self.team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=user, team=self.team, product_path="feature_flags", enabled=True)

        hardcoded_counts = [
            {"product_path": "product_analytics", "colleague_count": 5},
            {"product_path": "session_replay", "colleague_count": 4},
            {"product_path": "feature_flags", "colleague_count": 3},
            {"product_path": "surveys", "colleague_count": 2},
        ]

        created_items = UserProductList.sync_from_team_colleagues(
            user=user, team=self.team, count=2, colleague_product_counts=hardcoded_counts
        )

        assert len(created_items) == 2
        product_paths = {item.product_path for item in created_items}
        assert "product_analytics" not in product_paths
        assert "feature_flags" not in product_paths
        assert "session_replay" in product_paths
        assert "surveys" in product_paths

        all_user_products = UserProductList.objects.filter(user=user, team=self.team, enabled=True)
        assert all_user_products.filter(product_path="session_replay").exists()
        assert all_user_products.filter(product_path="surveys").exists()
        assert all_user_products.filter(product_path="product_analytics").exists()
        assert all_user_products.filter(product_path="feature_flags").exists()

        for item in created_items:
            assert item.reason == UserProductList.Reason.USED_BY_COLLEAGUES
            assert item.enabled is True

    def test_sync_ranks_by_precomputed_counts(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        hardcoded_counts = [
            {"product_path": "product_analytics", "colleague_count": 10},
            {"product_path": "session_replay", "colleague_count": 8},
            {"product_path": "feature_flags", "colleague_count": 5},
            {"product_path": "surveys", "colleague_count": 3},
            {"product_path": "experiments", "colleague_count": 1},
        ]

        created_items = UserProductList.sync_from_team_colleagues(
            user=user, team=self.team, count=3, colleague_product_counts=hardcoded_counts
        )

        assert len(created_items) == 3
        product_paths = [item.product_path for item in created_items]
        assert set(product_paths) == {"product_analytics", "session_replay", "feature_flags"}
        assert product_paths[0] == "product_analytics"
        assert product_paths[1] == "session_replay"
        assert product_paths[2] == "feature_flags"

    def test_sync_respects_count_limit(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        hardcoded_counts = [
            {"product_path": "product_analytics", "colleague_count": 10},
            {"product_path": "session_replay", "colleague_count": 8},
            {"product_path": "feature_flags", "colleague_count": 5},
            {"product_path": "surveys", "colleague_count": 3},
        ]

        created_items = UserProductList.sync_from_team_colleagues(
            user=user, team=self.team, count=2, colleague_product_counts=hardcoded_counts
        )

        assert len(created_items) == 2
        product_paths = {item.product_path for item in created_items}
        assert product_paths == {"product_analytics", "session_replay"}

    def test_sync_respects_allow_sidebar_suggestions_false(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=False
        )
        user.join(organization=self.organization)

        hardcoded_counts = [
            {"product_path": "product_analytics", "colleague_count": 10},
            {"product_path": "session_replay", "colleague_count": 8},
        ]

        created_items = UserProductList.sync_from_team_colleagues(
            user=user, team=self.team, colleague_product_counts=hardcoded_counts
        )

        assert len(created_items) == 0

    def test_sync_computes_counts_when_not_provided(self):
        colleague1 = User.objects.create_user(
            email="colleague1@posthog.com", password="password", first_name="Colleague1", allow_sidebar_suggestions=True
        )
        colleague2 = User.objects.create_user(
            email="colleague2@posthog.com", password="password", first_name="Colleague2", allow_sidebar_suggestions=True
        )
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )

        colleague1.join(organization=self.organization)
        colleague2.join(organization=self.organization)
        user.join(organization=self.organization)

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=colleague1, team=self.team, product_path="session_replay", enabled=True)

        created_items = UserProductList.sync_from_team_colleagues(user=user, team=self.team, count=2)

        assert len(created_items) == 2
        product_paths = {item.product_path for item in created_items}
        assert "product_analytics" in product_paths
        assert "session_replay" in product_paths

    def test_sync_does_not_duplicate_existing_products(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        UserProductList.objects.create(user=user, team=self.team, product_path="product_analytics", enabled=True)

        hardcoded_counts = [
            {"product_path": "product_analytics", "colleague_count": 10},
            {"product_path": "session_replay", "colleague_count": 8},
        ]

        created_items = UserProductList.sync_from_team_colleagues(
            user=user, team=self.team, colleague_product_counts=hardcoded_counts
        )

        assert len(created_items) == 1
        assert created_items[0].product_path == "session_replay"

        all_user_products = UserProductList.objects.filter(user=user, team=self.team, product_path="product_analytics")
        assert all_user_products.count() == 1

    def test_get_user_product_list_count(self):
        colleague1 = User.objects.create_user(
            email="colleague1@posthog.com", password="password", first_name="Colleague1", allow_sidebar_suggestions=True
        )
        colleague2 = User.objects.create_user(
            email="colleague2@posthog.com", password="password", first_name="Colleague2", allow_sidebar_suggestions=True
        )
        colleague3 = User.objects.create_user(
            email="colleague3@posthog.com", password="password", first_name="Colleague3", allow_sidebar_suggestions=True
        )
        colleague4 = User.objects.create_user(
            email="colleague4@posthog.com", password="password", first_name="Colleague4", allow_sidebar_suggestions=True
        )

        colleague1.join(organization=self.organization)
        colleague2.join(organization=self.organization)
        colleague3.join(organization=self.organization)
        colleague4.join(organization=self.organization)

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=colleague3, team=self.team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=colleague4, team=self.team, product_path="product_analytics", enabled=True)

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="session_replay", enabled=True)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="session_replay", enabled=True)
        UserProductList.objects.create(user=colleague3, team=self.team, product_path="session_replay", enabled=True)

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="feature_flags", enabled=True)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="feature_flags", enabled=True)

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="surveys", enabled=True)

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="experiments", enabled=False)

        counts = get_user_product_list_count(self.team)

        assert len(counts) == 4
        assert counts[0]["product_path"] == "product_analytics"
        assert counts[0]["colleague_count"] == 4
        assert counts[1]["product_path"] == "session_replay"
        assert counts[1]["colleague_count"] == 3
        assert counts[2]["product_path"] == "feature_flags"
        assert counts[2]["colleague_count"] == 2
        assert counts[3]["product_path"] == "surveys"
        assert counts[3]["colleague_count"] == 1

    def test_get_user_product_list_count_excludes_disabled_products(self):
        colleague1 = User.objects.create_user(
            email="colleague1@posthog.com", password="password", first_name="Colleague1", allow_sidebar_suggestions=True
        )
        colleague2 = User.objects.create_user(
            email="colleague2@posthog.com", password="password", first_name="Colleague2", allow_sidebar_suggestions=True
        )

        colleague1.join(organization=self.organization)
        colleague2.join(organization=self.organization)

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="product_analytics", enabled=True)
        UserProductList.objects.create(user=colleague1, team=self.team, product_path="session_replay", enabled=False)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="session_replay", enabled=False)

        counts = get_user_product_list_count(self.team)

        assert len(counts) == 1
        assert counts[0]["product_path"] == "product_analytics"
        assert counts[0]["colleague_count"] == 2

    def test_get_user_product_list_count_handles_empty_team(self):
        counts = get_user_product_list_count(self.team)
        assert len(counts) == 0
