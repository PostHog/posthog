from posthog.test.base import BaseTest

from posthog.schema import ProductItemCategory

from posthog.models import User
from posthog.models.file_system.user_product_list import (
    DEFAULT_PRODUCT_PATHS,
    UserProductList,
    add_default_products_for_user,
)
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
    def test_default_product_paths_are_valid_products(self):
        valid_paths = set(Products.get_product_paths())
        assert set(DEFAULT_PRODUCT_PATHS) <= valid_paths

    def test_add_default_products_creates_the_default_set(self):
        user = User.objects.create_user(email="user@posthog.com", password="password", first_name="User")
        user.join(organization=self.organization)

        created_items = add_default_products_for_user(user, self.team)

        assert {item.product_path for item in created_items} == set(DEFAULT_PRODUCT_PATHS)

        rows = UserProductList.objects.filter(user=user, team=self.team)
        assert {row.product_path for row in rows} == set(DEFAULT_PRODUCT_PATHS)
        for row in rows:
            assert row.enabled is True
            assert row.reason == UserProductList.Reason.DEFAULT

    def test_add_default_products_leaves_existing_rows_untouched(self):
        user = User.objects.create_user(email="user@posthog.com", password="password", first_name="User")
        user.join(organization=self.organization)

        UserProductList.objects.create(
            user=user,
            team=self.team,
            product_path="Product analytics",
            enabled=False,
            reason=UserProductList.Reason.PRODUCT_INTENT,
        )

        created_items = add_default_products_for_user(user, self.team)

        assert "Product analytics" not in {item.product_path for item in created_items}
        existing = UserProductList.objects.get(user=user, team=self.team, product_path="Product analytics")
        assert existing.enabled is False
        assert existing.reason == UserProductList.Reason.PRODUCT_INTENT

        add_default_products_for_user(user, self.team)
        assert UserProductList.objects.filter(user=user, team=self.team).count() == len(DEFAULT_PRODUCT_PATHS)

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
        assert tools_products
        assert "Web scripts" in tools_products
        UserProductList.objects.create(user=user, team=self.team, product_path="Web scripts", enabled=True)

        # Add a product from the Unreleased category
        assert unreleased_products
        UserProductList.objects.create(user=user, team=self.team, product_path=unreleased_products[0], enabled=True)

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
