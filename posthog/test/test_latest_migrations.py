import glob
import os
import pathlib
from unittest import TestCase


class TestLatestMigrations(TestCase):
    def test_posthog_migration_is_in_sync_with_latest(self) -> None:
        """
        regression test

        when manually merging and updating migrations it is possible for
        latest_migrations.manifest get out of sync with the migrations files

        this protects against that
        """
        latest_manifest_migration = self._get_latest_migration_from_manifest("posthog")
        latest_migration_file = self._get_newest_migration_file(f"{pathlib.Path().resolve()}/posthog/migrations/*")
        self.assertEqual(latest_manifest_migration, latest_migration_file)

    def test_ee_migrations_is_in_sync_with_latest(self):
        latest_manifest_migration = self._get_latest_migration_from_manifest("ee")
        latest_migration_file = self._get_newest_migration_file(f"{pathlib.Path().resolve()}/ee/migrations/*")
        self.assertEqual(latest_manifest_migration, latest_migration_file)

    @staticmethod
    def _get_newest_migration_file(path: str) -> str:
        migrations = [file for file in glob.glob(path) if file.endswith(".py") and not file.endswith("__init__.py")]
        latest_file = max(sorted(migrations))
        return os.path.basename(latest_file).replace(".py", "")

    @staticmethod
    def _get_latest_migration_from_manifest(django_app: str) -> str:
        root = pathlib.Path().resolve()
        manifest = pathlib.Path(f"{root}/latest_migrations.manifest").read_text()
        posthog_latest_migration = [line for line in manifest.splitlines() if line.startswith(f"{django_app}: ")][0]

        return posthog_latest_migration.replace(f"{django_app}: ", "")
