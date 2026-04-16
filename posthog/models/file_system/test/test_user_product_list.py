from posthog.test.base import BaseTest

from posthog.schema import ProductItemCategory

from posthog.models import User
from posthog.models.file_system.user_product_list import UserProductList, get_user_product_list_count
from posthog.products import Products

from products.growth.backend.cross_sell_candidate_selector import (
    BASE_PREFERENCE_WEIGHTS,
    DEFAULT_IGNORED_CATEGORIES,
    CrossSellCandidateSelector,
)


def _get_favored_product_paths() -> set[str]:
    """Derive the favored product paths from the selector constants."""
    selector = CrossSellCandidateSelector(user_enabled_products=set(), ignored_categories=DEFAULT_IGNORED_CATEGORIES)
    return {p for key in BASE_PREFERENCE_WEIGHTS for p in selector.intent_to_paths.get(key, [])}


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

    def test_sync_cross_sell_products_suggests_same_category_or_favored(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        UserProductList.objects.create(user=user, team=self.team, product_path="Product analytics", enabled=True)

        created_items = UserProductList.sync_cross_sell_products(user=user, team=self.team)

        by_category = Products.get_products_by_category()
        analytics_products = set(by_category.get(ProductItemCategory.ANALYTICS, []))
        # Favored products are always candidates even if from a different category
        favored_products = _get_favored_product_paths()
        valid_candidates = analytics_products | favored_products

        assert len(created_items) == 1
        for item in created_items:
            assert item.reason == UserProductList.Reason.USED_SIMILAR_PRODUCTS
            assert item.enabled is True
            assert item.product_path in valid_candidates
            assert item.product_path != "Product analytics"

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

        created_items = UserProductList.sync_cross_sell_products(user=user, team=self.team, max_products=3)
        assert 1 <= len(created_items) <= 3

    def test_sync_cross_sell_products_with_no_enabled_products_suggests_favored(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        created_items = UserProductList.sync_cross_sell_products(user=user, team=self.team)

        # Even with no enabled products, favored products are still candidates
        favored_products = _get_favored_product_paths()
        assert len(created_items) == 1
        assert created_items[0].product_path in favored_products

    def test_sync_cross_sell_products_candidates_include_same_category_and_favored(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        UserProductList.objects.create(user=user, team=self.team, product_path="Product analytics", enabled=True)

        products_by_category = Products.get_products_by_category()
        analytics_products = set(products_by_category.get(ProductItemCategory.ANALYTICS, []))
        favored_products = _get_favored_product_paths()
        valid_candidates = (analytics_products | favored_products) - {"Product analytics"}

        created_items = UserProductList.sync_cross_sell_products(user=user, team=self.team, max_products=5)

        created_paths = {item.product_path for item in created_items}
        for path in created_paths:
            assert path in valid_candidates

    def test_sync_cross_sell_products_ignores_tools_and_unreleased_categories(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        products_by_category = Products.get_products_by_category()
        tools_products = products_by_category.get(ProductItemCategory.TOOLS, [])
        unreleased_products = products_by_category.get(ProductItemCategory.UNRELEASED, [])

        # Add a product from the Tools category
        assert "Web scripts" in products_by_category.get(ProductItemCategory.TOOLS, [])
        UserProductList.objects.create(user=user, team=self.team, product_path="Web scripts", enabled=True)

        # Add a product from the Unreleased category
        assert "Links" in products_by_category.get(ProductItemCategory.UNRELEASED, [])
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
            user=user, team=self.team, ignored_categories=[ProductItemCategory.ANALYTICS]
        )

        products_by_category = Products.get_products_by_category()
        analytics_products = set(products_by_category.get(ProductItemCategory.ANALYTICS, []))

        created_paths = {item.product_path for item in created_items}
        assert not created_paths.intersection(analytics_products)

    def test_sync_cross_sell_products_falls_back_to_all_categories_when_no_same_category_or_favored(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        products_by_category = Products.get_products_by_category()
        favored_products = _get_favored_product_paths()

        # Enable all favored products and all products from a category so the first candidate set
        # (same-category + favored) would be empty, triggering the fallback to all categories.
        for path in favored_products:
            UserProductList.objects.create(user=user, team=self.team, product_path=path, enabled=True)
        analytics_products = set(products_by_category.get(ProductItemCategory.ANALYTICS, []))
        for path in analytics_products - favored_products:
            UserProductList.objects.create(user=user, team=self.team, product_path=path, enabled=True)

        created_items = UserProductList.sync_cross_sell_products(user=user, team=self.team)

        # Should still suggest something via the fallback to all non-ignored categories
        assert len(created_items) == 1
        tools_products = set(products_by_category.get(ProductItemCategory.TOOLS, []))
        unreleased_products = set(products_by_category.get(ProductItemCategory.UNRELEASED, []))
        assert created_items[0].product_path not in tools_products
        assert created_items[0].product_path not in unreleased_products
        assert created_items[0].product_path not in favored_products | analytics_products

    def test_sync_cross_sell_products_same_category_gets_weight_bump(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        UserProductList.objects.create(user=user, team=self.team, product_path="Product analytics", enabled=True)

        products_by_category = Products.get_products_by_category()
        analytics_products = set(products_by_category.get(ProductItemCategory.ANALYTICS, [])) - {"Product analytics"}

        all_created_paths: set[str] = set()
        for _ in range(50):
            items = UserProductList.sync_cross_sell_products(user=user, team=self.team)
            for item in items:
                all_created_paths.add(item.product_path)
            UserProductList.objects.filter(
                user=user, team=self.team, product_path__in=[i.product_path for i in items]
            ).exclude(product_path="Product analytics").delete()

        assert len(all_created_paths & analytics_products) > 0

    def test_sync_cross_sell_products_returns_empty_when_all_products_enabled(self):
        user = User.objects.create_user(
            email="user@posthog.com", password="password", first_name="User", allow_sidebar_suggestions=True
        )
        user.join(organization=self.organization)

        # Enable all products
        for product in Products.products():
            UserProductList.objects.create(user=user, team=self.team, product_path=product.path, enabled=True)

        created_items = UserProductList.sync_cross_sell_products(user=user, team=self.team)
        assert len(created_items) == 0

    def test_user_product_list_reason_enum_matches_backend(self):
        from posthog.schema import UserProductListReason

        backend_reasons = {key for key, _ in UserProductList.Reason.choices}
        schema_reasons = {value for _, value in UserProductListReason.__members__.items()}

        assert backend_reasons == schema_reasons, "Backend reasons do not match schema reasons"
