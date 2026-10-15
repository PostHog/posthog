from posthog.test.base import BaseTest

from dagster import build_op_context
from parameterized import parameterized

from posthog.dags.backfill_starred_products import MAX_PRODUCTS_TO_STAR, backfill_starred_products_op
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.models.file_system.starred_products import starred_products_setup_completed
from posthog.models.file_system.user_product_list import UserProductList
from posthog.models.team import Team
from posthog.models.user import User
from posthog.products import Products


class TestBackfillStarredProducts(BaseTest):
    def _starred_paths(self, user: User, team: Team) -> list[str]:
        return list(
            FileSystemShortcut.objects.filter(user=user, team=team).order_by("order").values_list("path", flat=True)
        )

    def _add_custom_products(self, user: User, team: Team, paths: list[str], *, enabled: bool = True) -> None:
        UserProductList.objects.bulk_create(
            [UserProductList(user=user, team=team, product_path=path, enabled=enabled) for path in paths]
        )

    def test_stars_small_lists_skips_long_lists_and_completes_setup(self) -> None:
        paths = sorted(Products.get_product_paths(), key=str.lower)[: MAX_PRODUCTS_TO_STAR + 1]
        user = User.objects.create_user(email="user@posthog.com", password="password", first_name="User")
        user.ui_configuration = {"version": 1, "sidebar": {"density": "compact"}}
        user.save()
        long_list_team = Team.objects.create(organization=self.organization, name="Long list")
        self._add_custom_products(user, self.team, paths[:MAX_PRODUCTS_TO_STAR])
        self._add_custom_products(user, self.team, [paths[MAX_PRODUCTS_TO_STAR]], enabled=False)
        self._add_custom_products(user, long_list_team, paths)

        result = backfill_starred_products_op(build_op_context(), [user.id])

        assert self._starred_paths(user, self.team) == paths[:MAX_PRODUCTS_TO_STAR]
        assert self._starred_paths(user, long_list_team) == []
        user.refresh_from_db()
        assert starred_products_setup_completed(user)
        assert (user.ui_configuration or {})["sidebar"]["density"] == "compact"
        assert result["users_migrated"] == 1
        assert result["projects_starred"] == 1
        assert result["projects_over_limit"] == 1

    @parameterized.expand([("dry_run", True), ("already_completed", False)])
    def test_writes_nothing(self, _name: str, dry_run: bool) -> None:
        user = User.objects.create_user(email="user@posthog.com", password="password", first_name="User")
        if not dry_run:
            user.ui_configuration = {"version": 1, "sidebar": {"starred_products_setup_completed": True}}
            user.save()
        self._add_custom_products(user, self.team, ["Session replay"])

        backfill_starred_products_op(build_op_context(op_config={"dry_run": dry_run}), [user.id])

        assert self._starred_paths(user, self.team) == []
        user.refresh_from_db()
        assert starred_products_setup_completed(user) is not dry_run

    def test_keeps_existing_stars_without_duplicating_them(self) -> None:
        user = User.objects.create_user(email="user@posthog.com", password="password", first_name="User")
        FileSystemShortcut.objects.create(team=self.team, user=user, path="Session replay", type="session_replay")
        self._add_custom_products(user, self.team, ["Error tracking", "Session replay"])

        backfill_starred_products_op(build_op_context(), [user.id])

        assert self._starred_paths(user, self.team) == ["Session replay", "Error tracking"]

    @parameterized.expand([("at_the_limit", 2, 6), ("over_the_limit", 3, 0)])
    def test_applies_the_limit_to_each_project_across_its_environments(
        self, _name: str, extra_in_second_environment: int, expected_stars: int
    ) -> None:
        paths = sorted(Products.get_product_paths(), key=str.lower)
        user = User.objects.create_user(email="user@posthog.com", password="password", first_name="User")
        second_environment = Team.objects.create(organization=self.organization, project=self.project, name="Staging")
        self._add_custom_products(user, self.team, paths[:4])
        # Two products overlap, so they count once.
        self._add_custom_products(user, second_environment, paths[2 : 4 + extra_in_second_environment])

        backfill_starred_products_op(build_op_context(), [user.id])

        starred = list(
            FileSystemShortcut.objects.filter(user=user, team__project_id=self.project.id).values_list(
                "path", flat=True
            )
        )
        assert sorted(starred, key=str.lower) == paths[: 4 + extra_in_second_environment][:expected_stars]
        assert len(starred) == len(set(starred))
