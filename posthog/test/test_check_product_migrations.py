from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from posthog.product_db_migrations import collect_unapplied_product_migrations, product_migration_alias
from posthog.product_db_router import get_product_db_routes


def _fake_apply_all_product_migrations() -> None:
    # Test product DBs are created with MIGRATE: False (tables come from syncdb),
    # so django_migrations starts empty; --fake records without executing DDL.
    for route in get_product_db_routes():
        call_command(
            "migrate",
            route.app_label,
            database=product_migration_alias(route.database),
            fake=True,
            interactive=False,
            verbosity=0,
        )


class TestCheckProductMigrations(TestCase):
    databases = "__all__"

    def test_fails_naming_unapplied_product_migrations(self) -> None:
        with self.assertRaises(CommandError) as ctx:
            call_command("check_product_migrations")

        self.assertIn("warehouse_sources_queue", str(ctx.exception))

    def test_passes_once_product_migrations_are_recorded(self) -> None:
        _fake_apply_all_product_migrations()

        call_command("check_product_migrations")

    def test_collect_can_be_scoped_to_one_database(self) -> None:
        unapplied = collect_unapplied_product_migrations(databases={"warehouse_sources_queue"})

        self.assertEqual(set(unapplied), {product_migration_alias("warehouse_sources_queue")})
