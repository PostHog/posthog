import os
import re
import sys
import logging

from git import Repo

from django.core.management.base import BaseCommand, CommandError


logger = logging.getLogger(__name__)
repo_path = os.getcwd()
repo = Repo(repo_path)
current_branch = repo.active_branch.name


class Command(BaseCommand):
    help = "Automated test to make sure ClickHouse migrations are safe"

    def handle(self, *args, **options):
        def run_and_check_migration(new_migration):
            repo.git.checkout("master")
            old_migration_files = os.listdir("posthog/clickhouse/migrations")
            old_migrations = []
            repo.git.checkout(current_branch)

            for migration in old_migration_files:
                match = re.findall(r"([0-9]+)_([a-zA-Z_0-9]+)\.py", migration)
                if len(match) == 0:
                    continue
                index, name = match[0]
                old_migrations.append((index, name))
            old_migrations.sort()

            for index, name in old_migrations:
                logger.info(f"old ClickHouse migration with index {index} and name {name} found")

            try:
                should_fail = False
                app, index, name = re.findall(
                    r"([a-z]+)\/clickhouse\/migrations\/([0-9]+)_([a-zA-Z_0-9]+)\.py", new_migration
                )[0]
                logger.info(f"new ClickHouse migration for app {app} with index {index} and name {name} found")

                matching_migration_indexes = []
                for old_index, old_name in old_migrations:
                    if old_index == index:
                        matching_migration_indexes.append((old_index, old_name))

                if len(matching_migration_indexes) > 1:
                    logger.error(f"Found an existing matching migrations with index {index} - PaNiC!")
                    logger.error("Colliding migrations are:")
                    for old_index, old_name in matching_migration_indexes:
                        logger.error(f"  - {old_index}_{old_name}")
                    logger.error(
                        "Please manually resolve this conflict and ensure all migrations are monotonically increasing"
                    )
                    should_fail = True

                if should_fail:
                    sys.exit(1)

            except (IndexError, CommandError):
                pass

        migrations = sys.stdin.readlines()

        if len(migrations) > 1:
            logger.error(
                f"\n\n\033[91mFound multiple migrations. Please scope PRs to one migration to promote easy debugging and revertability"
            )
            sys.exit(1)

        for data in migrations:
            run_and_check_migration(data)
