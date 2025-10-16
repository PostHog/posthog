from django.core.management.base import BaseCommand
from django.db import connections

import structlog

from posthog.clickhouse.client import sync_execute

logger = structlog.get_logger(__name__)

BATCH_SIZE = 10000
PROD_US_CUTOFF = "2025-10-01 00:00:00"


class Command(BaseCommand):
    help = "Sync cohort people records from ClickHouse person_static_cohort table to PostgreSQL posthog_cohortpeople table for records inserted after Oct 9, 2025 00:00 UTC"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size", type=int, default=BATCH_SIZE, help="Number of records to process in each batch"
        )
        parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
        parser.add_argument(
            "--start-date",
            type=str,
            default=PROD_US_CUTOFF,
            help="Start date for records to sync (format: 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD')",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]
        start_date = options["start_date"]

        if dry_run:
            self.stdout.write(self.style.WARNING("Running in dry-run mode - no changes will be made"))

        self.stdout.write(f"Configuration: batch_size={batch_size}, start_date={start_date}")

        # Determine the correct database connection for persons
        if "persons_db_reader" in connections:
            persons_db = "persons_db_reader"
        elif "replica" in connections:
            persons_db = "replica"
        else:
            persons_db = "default"

        self.stdout.write(f"Using database connection: {persons_db}")
        self.stdout.write(f"Starting cohort people sync for records after {start_date}")

        try:
            # Process ClickHouse data in batches and handle each batch completely
            total_inserted = 0
            cohorts_with_insertions = set()
            offset = 0

            while True:
                batch_query = """
                    SELECT DISTINCT person_id, cohort_id, team_id, _timestamp
                    FROM person_static_cohort
                    WHERE _timestamp >= %(cutoff_timestamp)s
                    ORDER BY _timestamp, person_id, cohort_id
                    LIMIT %(batch_size)s OFFSET %(offset)s
                """

                clickhouse_batch = sync_execute(
                    batch_query, {"cutoff_timestamp": start_date, "batch_size": batch_size, "offset": offset}
                )

                if not clickhouse_batch:
                    break

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Processing ClickHouse batch: {len(clickhouse_batch)} records (offset: {offset})"
                    )
                )

                # Extract unique person UUIDs from this batch
                ch_person_uuids = list({str(record[0]) for record in clickhouse_batch})

                if not ch_person_uuids:
                    offset += batch_size
                    continue

                # Use the correct database connection
                person_connection = connections[persons_db]

                # Get person ID mappings from persons database for this batch
                person_uuid_to_id = {}
                with person_connection.cursor() as cursor:
                    cursor.execute("SELECT uuid, id FROM posthog_person WHERE uuid = ANY(%s)", [ch_person_uuids])
                    for uuid, person_id in cursor.fetchall():
                        person_uuid_to_id[str(uuid)] = person_id

                if not person_uuid_to_id:
                    self.stdout.write(f"No matching persons found for batch at offset {offset}")
                    offset += batch_size
                    continue

                self.stdout.write(f"Found {len(person_uuid_to_id)} person ID mappings for batch")

                # Build the cohort data mapping from this ClickHouse batch
                cohort_data: dict[str, set[int]] = {}
                for record in clickhouse_batch:
                    record_person_uuid = str(record[0])
                    cohort_id = record[1]
                    if record_person_uuid not in cohort_data:
                        cohort_data[record_person_uuid] = set()
                    cohort_data[record_person_uuid].add(cohort_id)

                # Get existing cohortpeople records to avoid duplicates for this batch
                existing_pairs = set()
                with person_connection.cursor() as cursor:
                    person_ids = list(person_uuid_to_id.values())
                    if person_ids:
                        cursor.execute(
                            """
                            SELECT cohort_id, person_id
                            FROM posthog_cohortpeople
                            WHERE person_id = ANY(%s)
                        """,
                            [person_ids],
                        )
                        for cohort_id, person_id in cursor.fetchall():
                            existing_pairs.add((cohort_id, person_id))

                # Prepare bulk insert data for this batch, excluding existing records
                insert_values = []
                for person_uuid, cohort_ids in cohort_data.items():
                    if person_uuid not in person_uuid_to_id:
                        continue
                    person_id = person_uuid_to_id[person_uuid]
                    for cohort_id in cohort_ids:
                        if (cohort_id, person_id) not in existing_pairs:
                            insert_values.append((cohort_id, person_id))

                if insert_values:
                    if dry_run:
                        self.stdout.write(f"DRY RUN: Would insert {len(insert_values)} records")
                        # Show sample of what would be inserted
                        sample_size = min(5, len(insert_values))
                        for cohort_id, person_id in insert_values[:sample_size]:
                            self.stdout.write(f"  Would insert: cohort_id={cohort_id}, person_id={person_id}")
                        if sample_size < len(insert_values):
                            self.stdout.write(f"  ... and {len(insert_values) - sample_size} more records")

                        # Track cohorts that would have insertions in dry run
                        cohorts_in_batch = {cohort_id for cohort_id, _ in insert_values}
                        cohorts_with_insertions.update(cohorts_in_batch)
                    else:
                        # Insert this batch using Django ORM
                        from posthog.models.cohort.cohort import CohortPeople

                        # Create CohortPeople objects for bulk_create
                        cohort_people_objects = [
                            CohortPeople(cohort_id=cohort_id, person_id=person_id, version=0)
                            for cohort_id, person_id in insert_values
                        ]

                        created_objects = CohortPeople.objects.bulk_create(cohort_people_objects)
                        batch_inserted = len(created_objects)
                        total_inserted += batch_inserted

                        # Only track cohorts that actually had records inserted
                        if batch_inserted > 0:
                            cohorts_in_batch = {cohort_id for cohort_id, _ in insert_values}
                            cohorts_with_insertions.update(cohorts_in_batch)

                        self.stdout.write(self.style.SUCCESS(f"Batch successful: {batch_inserted} records inserted"))
                else:
                    self.stdout.write(f"No new records to insert for batch at offset {offset}")

                offset += batch_size

            if dry_run:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"DRY RUN COMPLETE: Would have inserted records into {len(cohorts_with_insertions)} cohorts"
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"Cohort people sync completed: {total_inserted} records inserted")
                )

                # Trigger cohort recalculation only for cohorts that had new people inserted
                if cohorts_with_insertions:
                    self.stdout.write(
                        f"Triggering recalculation for {len(cohorts_with_insertions)} cohorts: {list(cohorts_with_insertions)}"
                    )
                    try:
                        from posthog.models.cohort.cohort import Cohort
                        from posthog.tasks.calculate_cohort import increment_version_and_enqueue_calculate_cohort

                        for cohort in Cohort.objects.filter(id__in=cohorts_with_insertions).iterator():
                            try:
                                increment_version_and_enqueue_calculate_cohort(cohort, initiating_user=None)
                                self.stdout.write(f"Triggered recalculation for cohort {cohort.id}")
                            except Exception as e:
                                self.stdout.write(
                                    self.style.ERROR(f"Failed to trigger recalculation for cohort {cohort.id}: {e}")
                                )

                        self.stdout.write(self.style.SUCCESS("Completed cohort recalculation triggers"))
                    except ImportError as e:
                        self.stdout.write(self.style.ERROR(f"Could not import cohort calculation functions: {e}"))
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"Failed to trigger cohort recalculations: {e}"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error syncing cohort people: {e}"))
            raise
