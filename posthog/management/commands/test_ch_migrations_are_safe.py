import os
import re
import sys
import glob
import logging

from django.core.management.base import BaseCommand, CommandError

from git import Repo

logger = logging.getLogger(__name__)

CORE_MIGRATIONS_DIR = "posthog/clickhouse/migrations"
# Match any product that ships ClickHouse migrations alongside core.
PRODUCT_MIGRATIONS_GLOB = "products/*/backend/clickhouse/migrations"
MIGRATION_PATH_RE = re.compile(
    r"^(?:posthog/clickhouse/migrations|products/[a-z_]+/backend/clickhouse/migrations)/[0-9]+_[a-zA-Z_0-9]+\.py$"
)


def get_migration_dirs() -> list[str]:
    """Core dir plus every product that has opted into ClickHouse migrations."""
    dirs = [CORE_MIGRATIONS_DIR]
    dirs.extend(sorted(d for d in glob.glob(PRODUCT_MIGRATIONS_GLOB) if os.path.isdir(d)))
    return dirs


# Pre-existing duplicate migration numbers to ignore.
# DO NOT ADD NEW ENTRIES - fix the duplicate instead!
IGNORED_DUPLICATE_MIGRATION_NUMBERS = frozenset(
    [
        "0029",
        "0050",
        "0054",
        "0055",
        "0064",
        "0072",
        "0073",
        "0083",
    ]
)


def get_all_migrations(migrations_dir: str) -> list[tuple[str, str]]:
    """Get all migrations in a directory as (index, name) tuples."""
    migrations: list[tuple[str, str]] = []
    for filename in os.listdir(migrations_dir):
        match = re.match(r"([0-9]+)_([a-zA-Z_0-9]+)\.py", filename)
        if match:
            groups = match.groups()
            migrations.append((groups[0], groups[1]))
    return sorted(migrations, key=lambda x: (int(x[0]), x[1]))


def check_no_duplicate_migration_numbers(migrations_dir: str) -> bool:
    """Check for duplicate migration numbers (excluding known legacy duplicates)."""
    # Legacy duplicates only exist in core; products start clean.
    ignored = IGNORED_DUPLICATE_MIGRATION_NUMBERS if migrations_dir == CORE_MIGRATIONS_DIR else frozenset()
    seen: dict[str, list[str]] = {}
    for index, name in get_all_migrations(migrations_dir):
        seen.setdefault(index, []).append(name)

    duplicates = {idx: names for idx, names in seen.items() if len(names) > 1 and idx not in ignored}

    if duplicates:
        for index, names in sorted(duplicates.items()):
            logger.error(
                f"Duplicate migration in {migrations_dir} {index}: {', '.join(f'{index}_{n}.py' for n in names)}"
            )
        return False
    return True


def check_max_migration_file(migrations_dir: str) -> bool:
    """Check that max_migration.txt matches the highest numbered migration."""
    migrations = get_all_migrations(migrations_dir)
    if not migrations:
        return True

    max_migration = max(migrations, key=lambda x: (int(x[0]), x[1]))
    expected = f"{max_migration[0]}_{max_migration[1]}"

    max_migration_file = os.path.join(migrations_dir, "max_migration.txt")
    if not os.path.exists(max_migration_file):
        logger.error(f"{max_migration_file} not found")
        return False

    with open(max_migration_file) as f:
        actual = f.read().strip()

    if actual != expected:
        logger.error(f"{max_migration_file} outdated: has '{actual}', expected '{expected}'")
        return False
    return True


class Command(BaseCommand):
    help = "Automated test to make sure ClickHouse migrations are safe"

    def handle(self, *args, **options):
        for migrations_dir in get_migration_dirs():
            if not check_no_duplicate_migration_numbers(migrations_dir) or not check_max_migration_file(migrations_dir):
                sys.exit(1)

        if sys.stdin.isatty():
            logger.warning("Not running migration-specific checks. See .github/workflows/ci-backend.yml for usage.")
            return

        migrations = [m.strip() for m in sys.stdin.readlines() if m.strip() and MIGRATION_PATH_RE.match(m.strip())]

        # One migration per PR is enforced per package — a PR touching core and a product
        # is two files but one each, which is allowed.
        by_dir: dict[str, list[str]] = {}
        for migration in migrations:
            by_dir.setdefault(os.path.dirname(migration), []).append(migration)

        for migrations_dir, dir_migrations in by_dir.items():
            if len(dir_migrations) > 1:
                logger.error(f"Multiple migrations in PR for {migrations_dir}. Please limit to one migration per PR.")
                sys.exit(1)

        if not migrations:
            logger.info("No migrations to check.")
            return

        for new_migration in migrations:
            logger.info("Checking new migration %s", new_migration)
            self._check_migration_against_master(new_migration)

    @staticmethod
    def _check_migration_against_master(new_migration: str) -> None:
        """Check that new migration number doesn't conflict with migrations on master."""
        migrations_dir = os.path.dirname(new_migration)
        repo = Repo(os.getcwd())

        try:
            original_ref = repo.active_branch.name
        except TypeError:
            original_ref = repo.head.commit.hexsha

        try:
            repo.git.checkout("master")
            master_migrations = os.listdir(migrations_dir) if os.path.isdir(migrations_dir) else []
        finally:
            repo.git.checkout(original_ref)

        old_migrations = []
        for filename in master_migrations:
            match = re.findall(r"([0-9]+)_([a-zA-Z_0-9]+)\.py", filename)
            if match:
                old_migrations.append(match[0])

        try:
            index, name = re.findall(r"/([0-9]+)_([a-zA-Z_0-9]+)\.py$", new_migration)[0]
        except (IndexError, CommandError) as exc:
            logger.warning("Could not parse migration path '%s': %s", new_migration, exc)
            return

        collisions = [f"{idx}_{n}" for idx, n in old_migrations if idx == index]
        if collisions:
            logger.error(f"Migration {index}_{name} in {migrations_dir} conflicts with master: {', '.join(collisions)}")
            sys.exit(1)
