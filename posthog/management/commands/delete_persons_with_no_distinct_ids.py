import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Delete person rows that have no associated persondistinctid rows, by team"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Team ID to migrate from (on this instance)")
        parser.add_argument("--dry-run", action="store_false", help="Dry run mode (no changes will be made)")
        parser.add_argument(
            "--max-delete", default=1000, type=int, help="Max number of rows to delete in one go (default 1000)"
        )

    def handle(self, **options):
        team_id = options["team_id"]
        dry_run = options["dry_run"]
        max_delete = options["max_delete"]

        if not team_id:
            raise CommandError("source Team ID is required")

        print("Deleting persons with no distinct ids for team", team_id)  # noqa: T201

        if dry_run:
            print("Dry run mode enabled. No changes will be made.")  # noqa: T201
            delete_persons_without_distinct_ids_raw_sql_dry_run(team_id, max_delete)
        else:
            print("This is for real. Changes will be made. Sleeping for 10 seconds")  # noqa: T201
            time.sleep(10)
            delete_persons_without_distinct_ids_raw_sql(team_id, max_delete)


def delete_persons_without_distinct_ids_raw_sql(team_id, max_delete):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH persons_to_delete AS (
                SELECT p.id
                FROM posthog_person p
                LEFT JOIN posthog_persondistinctid pd ON p.id = pd.person_id AND p.team_id = pd.team_id
                WHERE p.team_id = %(team_id)s AND pd.id IS NULL
                LIMIT %(max_delete)s
            )
            DELETE FROM posthog_person
            WHERE id IN (SELECT id FROM persons_to_delete)
            RETURNING id;
        """,
            {"team_id": team_id, "max_delete": max_delete},
        )

        deleted_ids = cursor.fetchall()
        deleted_count = len(deleted_ids)

    print(f"Deleted {deleted_count} Person objects with no PersonDistinctIds for team {team_id}.")  # noqa: T201
    return deleted_count


def delete_persons_without_distinct_ids_raw_sql_dry_run(team_id, max_delete):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH persons_to_delete AS (
                SELECT p.id
                FROM posthog_person p
                LEFT JOIN posthog_persondistinctid pd ON p.id = pd.person_id AND p.team_id = pd.team_id
                WHERE p.team_id = %(team_id)s AND pd.id IS NULL
                LIMIT %(max_delete)s
            )
            SELECT COUNT(*) FROM persons_to_delete;
        """,
            {"team_id": team_id, "max_delete": max_delete},
        )

        deleted_count = cursor.fetchone()
        deleted_count = deleted_count[0] if deleted_count else 0

    print(f"Would have deleted {deleted_count} Person objects with no PersonDistinctIds for team {team_id}.")  # noqa: T201
    return deleted_count
