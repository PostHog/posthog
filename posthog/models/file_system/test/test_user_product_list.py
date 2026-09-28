from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import ProductIntent, Team, User
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.models.file_system.starred_products import starred_products_setup_completed
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


class TestStarCustomProductsForSimpleSidebar(BaseTest):
    def _starred(self, user: User) -> dict[str, str]:
        return dict(FileSystemShortcut.objects.filter(user=user, team=self.team).values_list("path", "type"))

    @parameterized.expand(
        [
            ("brand_new_user_on_flag", True, False, False, set(DEFAULT_PRODUCT_PATHS), True),
            ("brand_new_user_off_flag", False, False, False, set(), False),
            ("existing_user_mid_migration", True, True, False, set(), False),
            ("user_who_finished_setup", True, True, True, set(DEFAULT_PRODUCT_PATHS), True),
        ]
    )
    def test_default_products_are_starred_only_for_flagged_new_or_finished_users(
        self,
        _name: str,
        flag_enabled: bool,
        has_custom_products: bool,
        setup_completed: bool,
        expected_starred: set[str],
        expected_completed: bool,
    ) -> None:
        user = User.objects.create_user(email="user@posthog.com", password="password", first_name="User")
        if has_custom_products:
            other_team = Team.objects.create(organization=self.organization, name="Other")
            UserProductList.objects.create(user=user, team=other_team, product_path="Logs", enabled=True)
        if setup_completed:
            user.ui_configuration = {
                "version": 1,
                "sidebar": {"density": "compact", "starred_products_setup_completed": True},
            }
            user.save()

        with patch(
            "posthog.models.file_system.starred_products.posthoganalytics.feature_enabled", return_value=flag_enabled
        ):
            add_default_products_for_user(user, self.team)

        assert set(self._starred(user)) == expected_starred
        user.refresh_from_db()
        assert starred_products_setup_completed(user) is expected_completed
        if setup_completed:
            assert user.ui_configuration["sidebar"]["density"] == "compact"

    def test_product_intent_stars_only_new_products_without_duplicates(self) -> None:
        user = User.objects.create_user(email="user@posthog.com", password="password", first_name="User")
        user.ui_configuration = {"version": 1, "sidebar": {"starred_products_setup_completed": True}}
        user.save()
        FileSystemShortcut.objects.create(team=self.team, user=user, path="Session replay", type="session_replay")
        intent = ProductIntent.objects.create(team=self.team, product_type="session_replay")

        with patch("posthog.models.file_system.starred_products.posthoganalytics.feature_enabled", return_value=True):
            UserProductList.create_from_product_intent(intent, user)
            UserProductList.create_from_product_intent(intent, user)

        assert FileSystemShortcut.objects.filter(user=user, team=self.team, path="Session replay").count() == 1
        assert set(self._starred(user)) == {
            product.path for product in Products.get_products_by_intent("session_replay")
        }
