# ruff: noqa: T201 allow print statements

import os
import re
import sys
import select

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from posthog.management.migration_sql_checks import validate_migration_sql


class Command(BaseCommand):
    help = "Automated test to make sure there are no non-null, dropping, renaming, or multiple migrations"

    def handle(self, *args, **options):
        def run_and_check_migration(variable):
            try:
                # Handle both posthog/migrations and products/*/backend/migrations paths
                # For products: products/product_name/backend/migrations/0001_initial.py -> (product_name, 0001_initial)
                # For posthog: posthog/migrations/0001_initial.py -> (posthog, 0001_initial)
                products_match = re.findall(r"products/([a-z_]+)/backend/migrations/([a-zA-Z_0-9]+)\.py", variable)
                if products_match:
                    results = products_match[0]
                else:
                    results = re.findall(r"([a-z]+)\/migrations\/([a-zA-Z_0-9]+)\.py", variable)[0]

                sql = call_command("sqlmigrate", results[0], results[1])
                should_fail = validate_migration_sql(sql)
                if should_fail:
                    sys.exit(1)

            except IndexError:
                print(f"\n\n\033[93m⚠️  WARNING: Could not parse migration path: {variable.strip()}\033[0m")
                print(
                    "Expected format: posthog/migrations/NNNN_name.py or products/name/backend/migrations/NNNN_name.py"
                )
                if os.getenv("CI"):
                    print("\033[91mFailing in CI due to unparseable migration path\033[0m")
                    sys.exit(1)
            except CommandError as e:
                print(f"\n\n\033[93m⚠️  WARNING: Failed to run sqlmigrate for {variable.strip()}\033[0m")
                print(f"Error: {e}")
                if os.getenv("CI"):
                    print("\033[91mFailing in CI due to sqlmigrate error\033[0m")
                    sys.exit(1)

        # Wait for stdin with 1 second timeout
        if select.select([sys.stdin], [], [], 1)[0]:
            migrations = sys.stdin.readlines()
        else:
            if os.getenv("CI"):
                print("\n\n\033[91mNo migrations provided in CI - this is likely a mistake")
                sys.exit(1)
            print("No stdin detected, using default migrations - only useful for testing purposes.")
            migrations = []

        if not migrations:
            migrations = ["posthog/migrations/0771_teamrevenueanalyticsconfig_filter_test_accounts_and_more.py"]

        if len(migrations) > 1:
            print(
                f"\n\n\033[91mFound multiple migrations. Please scope PRs to one migration to promote easy debugging and revertability"
            )
            sys.exit(1)

        for data in migrations:
            data = data.strip()
            # Skip empty lines
            if not data:
                continue
            # Validate file extension
            if not data.endswith(".py"):
                print(f"\033[93m⚠️  Skipping non-Python file: {data}\033[0m")
                continue
            # Prevent path traversal
            if ".." in data or data.startswith("/"):
                print(f"\033[91m⚠️  Skipping suspicious path: {data}\033[0m")
                if os.getenv("CI"):
                    sys.exit(1)
                continue
            run_and_check_migration(data)
