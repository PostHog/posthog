from posthog.test.base import BaseTest

from posthog.models import User
from posthog.models.file_system.user_product_list import (
    DEFAULT_PRODUCT_PATHS,
    UserProductList,
    add_default_products_for_user,
)
from posthog.products import Products


class TestUserProductList(BaseTest):
    def test_default_product_paths_are_valid_products(self):
        valid_paths = set(Products.get_product_paths())
        assert set(DEFAULT_PRODUCT_PATHS) <= valid_paths

    def test_add_default_products_creates_the_default_set(self):
        user = User.objects.create_user(email="user@posthog.com", password="password", first_name="User")

        created_items = add_default_products_for_user(user, self.team)

        assert {item.product_path for item in created_items} == set(DEFAULT_PRODUCT_PATHS)

        rows = UserProductList.objects.filter(user=user, team=self.team)
        assert {row.product_path for row in rows} == set(DEFAULT_PRODUCT_PATHS)
        for row in rows:
            assert row.enabled is True

    def test_add_default_products_leaves_existing_rows_untouched(self):
        user = User.objects.create_user(email="user@posthog.com", password="password", first_name="User")

        UserProductList.objects.create(
            user=user,
            team=self.team,
            product_path="Product analytics",
            enabled=False,
        )

        created_items = add_default_products_for_user(user, self.team)

        assert "Product analytics" not in {item.product_path for item in created_items}
        existing = UserProductList.objects.get(user=user, team=self.team, product_path="Product analytics")
        assert existing.enabled is False

        add_default_products_for_user(user, self.team)
        assert UserProductList.objects.filter(user=user, team=self.team).count() == len(DEFAULT_PRODUCT_PATHS)

    def test_join_seeds_default_products_for_accessible_teams(self):
        # Guards joins that don't go through an invite (e.g. domain/SSO auto-join):
        # seeding must live in User.join itself, not only in the invite flow.
        user = User.objects.create_user(email="joiner@posthog.com", password="password", first_name="Joiner")

        user.join(organization=self.organization)

        rows = UserProductList.objects.filter(user=user, team=self.team)
        assert {row.product_path for row in rows} == set(DEFAULT_PRODUCT_PATHS)
        for row in rows:
            assert row.enabled is True
