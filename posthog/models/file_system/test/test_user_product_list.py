from posthog.test.base import BaseTest

from posthog.models import User
from posthog.models.file_system.user_product_list import UserProductList, get_user_product_list_count
from posthog.products import Products


class TestUserProductList(BaseTest):
    def test_sync_filters_out_existing_products_with_precomputed_counts(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        UserProductList.objects.create(user=user, team=self.team, product_path="Product analytics", enabled=True)
        UserProductList.objects.create(user=user, team=self.team, product_path="Feature flags", enabled=True)

        hardcoded_counts = [
            {"product_path": "Product analytics", "colleague_count": 5},
            {"product_path": "Session replay", "colleague_count": 4},
            {"product_path": "Feature flags", "colleague_count": 3},
            {"product_path": "Surveys", "colleague_count": 2},
        ]

        created_items = UserProductList.sync_from_team_colleagues(
            user=user, team=self.team, count=2, colleague_product_counts=hardcoded_counts
        )

        assert len(created_items) == 2
        product_paths = {item.product_path for item in created_items}
        assert "Product analytics" not in product_paths
        assert "Feature flags" not in product_paths
        assert "Session replay" in product_paths
        assert "Surveys" in product_paths

        all_user_products = UserProductList.objects.filter(user=user, team=self.team, enabled=True)
        assert all_user_products.filter(product_path="Session replay").exists()
        assert all_user_products.filter(product_path="Surveys").exists()
        assert all_user_products.filter(product_path="Product analytics").exists()
        assert all_user_products.filter(product_path="Feature flags").exists()

        for item in created_items:
            assert item.reason == UserProductList.Reason.USED_BY_COLLEAGUES
            assert item.enabled is True

    def test_sync_ranks_by_precomputed_counts(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        hardcoded_counts = [
            {"product_path": "Product analytics", "colleague_count": 10},
            {"product_path": "Session replay", "colleague_count": 8},
            {"product_path": "Feature flags", "colleague_count": 5},
            {"product_path": "Surveys", "colleague_count": 3},
            {"product_path": "Experiments", "colleague_count": 1},
        ]

        created_items = UserProductList.sync_from_team_colleagues(
            user=user, team=self.team, count=3, colleague_product_counts=hardcoded_counts
        )

        assert len(created_items) == 3
        product_paths = [item.product_path for item in created_items]
        assert set(product_paths) == {"Product analytics", "Session replay", "Feature flags"}
        assert product_paths[0] == "Product analytics"
        assert product_paths[1] == "Session replay"
        assert product_paths[2] == "Feature flags"

    def test_sync_respects_count_limit(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        hardcoded_counts = [
            {"product_path": "Product analytics", "colleague_count": 10},
            {"product_path": "Session replay", "colleague_count": 8},
            {"product_path": "Feature flags", "colleague_count": 5},
            {"product_path": "Surveys", "colleague_count": 3},
        ]

        created_items = UserProductList.sync_from_team_colleagues(
            user=user, team=self.team, count=2, colleague_product_counts=hardcoded_counts
        )

        assert len(created_items) == 2
        product_paths = {item.product_path for item in created_items}
        assert product_paths == {"Product analytics", "Session replay"}

    def test_sync_respects_allow_sidebar_suggestions_false(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=False
        )
        user.join(organization=self.organization)

        hardcoded_counts = [
            {"product_path": "Product analytics", "colleague_count": 10},
            {"product_path": "Session replay", "colleague_count": 8},
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

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="Product analytics", enabled=True)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="Product analytics", enabled=True)
        UserProductList.objects.create(user=colleague1, team=self.team, product_path="Session replay", enabled=True)

        created_items = UserProductList.sync_from_team_colleagues(user=user, team=self.team, count=2)

        assert len(created_items) == 2
        product_paths = {item.product_path for item in created_items}
        assert "Product analytics" in product_paths
        assert "Session replay" in product_paths

    def test_sync_does_not_duplicate_existing_products(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        UserProductList.objects.create(user=user, team=self.team, product_path="Product analytics", enabled=True)

        hardcoded_counts = [
            {"product_path": "Product analytics", "colleague_count": 10},
            {"product_path": "Session replay", "colleague_count": 8},
        ]

        created_items = UserProductList.sync_from_team_colleagues(
            user=user, team=self.team, colleague_product_counts=hardcoded_counts
        )

        assert len(created_items) == 1
        assert created_items[0].product_path == "Session replay"

        all_user_products = UserProductList.objects.filter(user=user, team=self.team, product_path="Product analytics")
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

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="Product analytics", enabled=True)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="Product analytics", enabled=True)
        UserProductList.objects.create(user=colleague3, team=self.team, product_path="Product analytics", enabled=True)
        UserProductList.objects.create(user=colleague4, team=self.team, product_path="Product analytics", enabled=True)

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="Session replay", enabled=True)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="Session replay", enabled=True)
        UserProductList.objects.create(user=colleague3, team=self.team, product_path="Session replay", enabled=True)

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="Feature flags", enabled=True)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="Feature flags", enabled=True)

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="Surveys", enabled=True)

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="Experiments", enabled=False)

        counts = get_user_product_list_count(self.team)

        assert len(counts) == 4
        assert counts[0]["product_path"] == "Product analytics"
        assert counts[0]["colleague_count"] == 4
        assert counts[1]["product_path"] == "Session replay"
        assert counts[1]["colleague_count"] == 3
        assert counts[2]["product_path"] == "Feature flags"
        assert counts[2]["colleague_count"] == 2
        assert counts[3]["product_path"] == "Surveys"
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

        UserProductList.objects.create(user=colleague1, team=self.team, product_path="Product analytics", enabled=True)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="Product analytics", enabled=True)
        UserProductList.objects.create(user=colleague1, team=self.team, product_path="Session replay", enabled=False)
        UserProductList.objects.create(user=colleague2, team=self.team, product_path="Session replay", enabled=False)

        counts = get_user_product_list_count(self.team)

        assert len(counts) == 1
        assert counts[0]["product_path"] == "Product analytics"
        assert counts[0]["colleague_count"] == 2

    def test_get_user_product_list_count_handles_empty_team(self):
        counts = get_user_product_list_count(self.team)
        assert len(counts) == 0

    def test_sync_cross_sell_products_suggests_same_category(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        UserProductList.objects.create(user=user, team=self.team, product_path="Product analytics", enabled=True)

        created_items = UserProductList.sync_cross_sell_products(user=user, team=self.team)

        by_category = Products.get_products_by_category()
        analytics_category = by_category.get("Analytics")
        assert analytics_category is not None

        assert len(created_items) >= 0
        for item in created_items:
            assert item.reason == UserProductList.Reason.USED_SIMILAR_PRODUCTS
            assert item.enabled is True
            assert item.product_path in analytics_category

    def test_sync_cross_sell_products_excludes_existing_products(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        UserProductList.objects.create(user=user, team=self.team, product_path="Product analytics", enabled=True)
        UserProductList.objects.create(user=user, team=self.team, product_path="Dashboards", enabled=True)

        created_items: list[UserProductList] = []
        while True:
            items = UserProductList.sync_cross_sell_products(user=user, team=self.team)
            if len(items) == 0:
                break
            created_items.extend(items)

        created_paths = {item.product_path for item in created_items}
        assert "Product analytics" not in created_paths
        assert "Dashboards" not in created_paths

    def test_sync_cross_sell_products_respects_allow_sidebar_suggestions_false(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=False
        )
        user.join(organization=self.organization)

        UserProductList.objects.create(user=user, team=self.team, product_path="Product analytics", enabled=True)

        created_items = UserProductList.sync_cross_sell_products(user=user, team=self.team)
        assert len(created_items) == 0

    def test_sync_cross_sell_products_respects_max_products(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        UserProductList.objects.create(user=user, team=self.team, product_path="Product analytics", enabled=True)

        created_items = UserProductList.sync_cross_sell_products(user=user, team=self.team, max_products=2)
        assert len(created_items) == 2

    def test_sync_cross_sell_products_handles_empty_cross_sell_options(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        created_items = UserProductList.sync_cross_sell_products(user=user, team=self.team)
        assert len(created_items) == 0

    def test_sync_cross_sell_products_suggests_from_analytics_category(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        UserProductList.objects.create(user=user, team=self.team, product_path="Product analytics", enabled=True)

        created_items = UserProductList.sync_cross_sell_products(user=user, team=self.team)

        products_by_category = Products.get_products_by_category()
        analytics_products = set(products_by_category.get("Analytics", []))

        created_paths = {item.product_path for item in created_items}
        for path in created_paths:
            assert path in analytics_products
            assert path != "Product analytics"

    def test_sync_cross_sell_products_ignores_tools_and_unreleased_categories(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        products_by_category = Products.get_products_by_category()
        tools_products = products_by_category.get("Tools", [])
        unreleased_products = products_by_category.get("Unreleased", [])

        # Add a product from the Tools category
        assert "Data pipelines" in products_by_category.get("Tools", [])
        UserProductList.objects.create(user=user, team=self.team, product_path="Data pipelines", enabled=True)

        # Add a product from the Unreleased category
        assert "Links" in products_by_category.get("Unreleased", [])
        UserProductList.objects.create(user=user, team=self.team, product_path="Links", enabled=True)

        created_items = UserProductList.sync_cross_sell_products(user=user, team=self.team)
        created_paths = {item.product_path for item in created_items}
        assert not created_paths.intersection(tools_products)
        assert not created_paths.intersection(unreleased_products)

    def test_sync_cross_sell_products_respects_custom_ignored_categories(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        UserProductList.objects.create(user=user, team=self.team, product_path="Product analytics", enabled=True)

        created_items = UserProductList.sync_cross_sell_products(
            user=user, team=self.team, ignored_categories=["Analytics"]
        )

        products_by_category = Products.get_products_by_category()
        analytics_products = set(products_by_category.get("Analytics", []))

        created_paths = {item.product_path for item in created_items}
        assert not created_paths.intersection(analytics_products)

    def test_user_product_list_reason_enum_matches_backend(self):
        """Test that the frontend UserProductListReason enum matches the backend Reason choices."""
        from posthog.schema import UserProductListReason

        backend_reasons = {key for key, _ in UserProductList.Reason.choices}
        schema_reasons = {value for _, value in UserProductListReason.__members__.items()}

        assert backend_reasons == schema_reasons, "Backend reasons do not match schema reasons"
