import logging

from django.db import connection
import structlog
from django.core.management.base import BaseCommand


logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Fix state for person distinct IDs in ClickHouse after person deletion and id re-use for a single team"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Specify a team to fix data for.")
        parser.add_argument(
            "--person-ids", default=None, type=str, help="Specify a list of comma separated person ids to be deleted."
        )
        parser.add_argument("--limit", default=100, type=int, help="Number of rows to be deleted")
        parser.add_argument("--live-run", action="store_true", help="Run changes, default is dry-run")

    def handle(self, *args, **options):
        run(options)


def run(options, sync: bool = False):
    live_run = options["live_run"]
    team_id = options["team_id"]
    person_ids = options["person_ids"].split(",") if options["person_ids"] else None
    limit = options["limit"]

    if not team_id:
        logger.error("You must specify --team-id to run this script")
        return exit(1)

    # Print the plan
    logger.info("Plan:")
    if team_id:
        logger.info(f"-> Team ID: {team_id}")
    if person_ids:
        logger.info(f"-> Person IDs: {person_ids}")
    logger.info(f"-> Limit: {limit} ")

    select_query = f"""
        SELECT id
        FROM posthog_person
        WHERE team_id=%(team_id)s {f"AND id IN ({person_ids})" if person_ids else ""}
        ORDER BY id ASC
        LIMIT %(limit)s
    """

    delete_query_person_distinct_ids = f"""
    WITH to_delete AS ({select_query})
    DELETE FROM posthog_persondistinctid
    WHERE team_id = %(team_id)s AND person_id IN (SELECT id FROM to_delete);
    """

    delete_query_person_override = f"""
    WITH to_delete AS ({select_query})
    DELETE FROM posthog_personoverride
    WHERE team_id = %(team_id)s AND (old_person_id IN (SELECT id FROM to_delete) OR override_person_id IN (SELECT id FROM to_delete));
    """

    delete_query_person = f"""
    WITH to_delete AS ({select_query})
    DELETE FROM posthog_person
    WHERE team_id = %(team_id)s AND id IN (SELECT id FROM to_delete);
    """

    with connection.cursor() as cursor:
        prepared_person_distinct_ids_query = cursor.mogrify(
            delete_query_person_distinct_ids, {"team_id": team_id, "limit": limit, "person_ids": person_ids}
        )
        prepared_person_override_query = cursor.mogrify(
            delete_query_person_override, {"team_id": team_id, "limit": limit, "person_ids": person_ids}
        )
        prepared_person_query = cursor.mogrify(
            delete_query_person, {"team_id": team_id, "limit": limit, "person_ids": person_ids}
        )

    logger.info(f"Delete query to run:")
    logger.info(prepared_person_distinct_ids_query)
    logger.info(prepared_person_override_query)
    logger.info(prepared_person_query)

    if not live_run:
        logger.info(f"Dry run. Set --live-run to actually delete.")
        return exit(0)

    confirm = input("Type 'delete' to confirm: ")

    if confirm != "delete":
        logger.info("Aborting")
        return exit(0)

    logger.info(f"Executing delete query...")

    # distinct_ids are deleted by cascade
    with connection.cursor() as cursor:
        cursor.execute(delete_query_person_distinct_ids, {"team_id": team_id, "limit": limit, "person_ids": person_ids})
        logger.info(f"Deleted {cursor.rowcount} distinct_ids")
        cursor.execute(delete_query_person_override, {"team_id": team_id, "limit": limit, "person_ids": person_ids})
        logger.info(f"Deleted {cursor.rowcount} person overrides")
        cursor.execute(delete_query_person, {"team_id": team_id, "limit": limit, "person_ids": person_ids})
        logger.info(f"Deleted {cursor.rowcount} persons")

    logger.info("Done")
