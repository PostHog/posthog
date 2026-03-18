from collections.abc import Callable
from dataclasses import asdict, dataclass

from django.core.management.base import BaseCommand
from django.db import connection, connections

from psycopg import sql

from posthog.models.person import Person


@dataclass(frozen=True)
class DeleteOptions:
    team_id: int
    person_ids: list[int]
    batch_size: int
    batches: int
    live_run: bool
    write: Callable[[str], None]

    @property
    def for_specific_persons(self) -> bool:
        return len(self.person_ids) > 0


@dataclass(frozen=True)
class DeleteBatchResult:
    distinct_ids_deleted: int
    person_overrides_deleted: int
    cohort_people_deleted: int
    persons_deleted: int


@dataclass(frozen=True)
class DeleteQueries:
    person_distinct_ids: sql.Composed
    person_override: sql.Composed
    cohort_people: sql.Composed
    person: sql.Composed


def build_delete_queries(*, for_specific_persons: bool) -> DeleteQueries:
    """
    Build SQL queries for deleting persons and related records.

    Uses sql.Identifier to safely escape table names (protection against SQL injection).
    Uses parameterized queries for all values.
    """
    person_table = sql.Identifier(Person._meta.db_table)

    if for_specific_persons:
        select_query = sql.SQL("""
            SELECT id
            FROM {person_table}
            WHERE team_id=%(team_id)s AND id = ANY(%(person_ids)s::integer[])
            ORDER BY id ASC
            LIMIT %(limit)s
        """).format(person_table=person_table)
    else:
        select_query = sql.SQL("""
            SELECT id
            FROM {person_table}
            WHERE team_id=%(team_id)s
            ORDER BY id ASC
            LIMIT %(limit)s
        """).format(person_table=person_table)

    return DeleteQueries(
        person_distinct_ids=sql.SQL("""
            WITH to_delete AS ({select_query})
            DELETE FROM posthog_persondistinctid
            WHERE person_id IN (SELECT id FROM to_delete);
        """).format(select_query=select_query),
        person_override=sql.SQL("""
            WITH to_delete AS ({select_query})
            DELETE FROM posthog_personoverride
            WHERE (old_person_id IN (SELECT id FROM to_delete) OR override_person_id IN (SELECT id FROM to_delete));
        """).format(select_query=select_query),
        cohort_people=sql.SQL("""
            WITH to_delete AS ({select_query})
            DELETE FROM posthog_cohortpeople
            WHERE person_id IN (SELECT id FROM to_delete);
        """).format(select_query=select_query),
        person=sql.SQL("""
            WITH to_delete AS ({select_query})
            DELETE FROM {person_table}
            WHERE id IN (SELECT id FROM to_delete);
        """).format(select_query=select_query, person_table=person_table),
    )


def delete_persons_batch(team_id: int, person_ids: list[int], batch_size: int) -> DeleteBatchResult:
    """
    Delete a batch of persons and their related records from postgres.

    Args:
        team_id: The team to delete persons from
        person_ids: List of specific person IDs to delete. Empty list means all persons for the team.
        batch_size: Maximum number of persons to delete in this batch

    Returns:
        Counts of deleted records for each table
    """
    for_specific_persons = len(person_ids) > 0
    queries = build_delete_queries(for_specific_persons=for_specific_persons)
    params: dict[str, int | list[int]] = {"team_id": team_id, "limit": batch_size, "person_ids": person_ids}

    conn = connections["persons_db_writer"] if "persons_db_writer" in connections else connection
    with conn.cursor() as cursor:
        cursor.execute(queries.person_distinct_ids, params)
        distinct_ids_deleted = cursor.rowcount

        cursor.execute(queries.person_override, params)
        person_overrides_deleted = cursor.rowcount

        cursor.execute(queries.cohort_people, params)
        cohort_people_deleted = cursor.rowcount

        cursor.execute(queries.person, params)
        persons_deleted = cursor.rowcount

    return DeleteBatchResult(
        distinct_ids_deleted=distinct_ids_deleted,
        person_overrides_deleted=person_overrides_deleted,
        cohort_people_deleted=cohort_people_deleted,
        persons_deleted=persons_deleted,
    )


class Command(BaseCommand):
    help = "Delete a batch of persons from postgres"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Specify a team to delete persons from.")
        parser.add_argument(
            "--person-ids", default=None, type=str, help="Specify a list of comma separated person ids to be deleted."
        )
        parser.add_argument(
            "--delete-all-persons-for-team",
            action="store_true",
            help="Delete ALL persons for the team. Required if --person-ids is not provided.",
        )
        parser.add_argument("--batch-size", default=1000, type=int, help="Number of rows to be deleted per batch")
        parser.add_argument("--batches", default=1, type=int, help="Number of batches to run")
        parser.add_argument("--live-run", action="store_true", help="Run changes, default is dry-run")

    def handle(self, *args, **options):
        team_id = options["team_id"]
        if not team_id:
            self.stderr.write("ERROR: You must specify --team-id to run this script")
            return exit(1)

        person_ids_raw = options["person_ids"]
        person_ids = [int(pid.strip()) for pid in person_ids_raw.split(",") if pid.strip()] if person_ids_raw else []
        delete_all = options["delete_all_persons_for_team"]

        if person_ids_raw and not person_ids:
            self.stderr.write("ERROR: --person-ids was provided but contained no valid IDs")
            return exit(1)

        if not person_ids and not delete_all:
            self.stderr.write("ERROR: You must specify --person-ids or --delete-all-persons-for-team")
            return exit(1)

        if person_ids and delete_all:
            self.stderr.write("ERROR: Cannot specify both --person-ids and --delete-all-persons-for-team")
            return exit(1)

        opts = DeleteOptions(
            team_id=team_id,
            person_ids=person_ids,
            batch_size=options["batch_size"],
            batches=options["batches"],
            live_run=options["live_run"],
            write=self.stdout.write,
        )
        run(opts)


def run(opts: DeleteOptions):
    write = opts.write

    write("Plan:")
    write(f"-> Team ID: {opts.team_id}")
    if opts.person_ids:
        write(f"-> Person IDs: {opts.person_ids}")
    else:
        write("-> Deleting ALL persons for team")
    write(f"-> Batches: {opts.batches} of {opts.batch_size}")

    queries = build_delete_queries(for_specific_persons=opts.for_specific_persons)
    params: dict[str, int | list[int]] = {
        "team_id": opts.team_id,
        "limit": opts.batch_size,
        "person_ids": opts.person_ids,
    }

    conn = connections["persons_db_writer"] if "persons_db_writer" in connections else connection
    with conn.cursor() as cursor:
        prepared_queries = {name: cursor.mogrify(query, params) for name, query in asdict(queries).items()}

    write("Delete queries to run:")
    for name, prepared_query in prepared_queries.items():
        write(f"{name}: {prepared_query}")

    if not opts.live_run:
        write("Dry run. Set --live-run to actually delete.")
        return exit(0)

    confirm = input("Type 'delete' to confirm: ")

    if confirm != "delete":
        write("Aborting")
        return exit(0)

    write("Executing delete queries...")

    for i in range(opts.batches):
        write(f"Deleting batch {i + 1} of {opts.batches} ({opts.batch_size} rows)")
        result = delete_persons_batch(opts.team_id, opts.person_ids, opts.batch_size)
        write(f"Deleted {result.distinct_ids_deleted} distinct_ids")
        write(f"Deleted {result.person_overrides_deleted} person overrides")
        write(f"Deleted {result.cohort_people_deleted} cohort people")
        write(f"Deleted {result.persons_deleted} persons")

        if result.persons_deleted < opts.batch_size:
            write(f"Exiting early as we received less than {opts.batch_size} rows")
            break

    write("Done")
