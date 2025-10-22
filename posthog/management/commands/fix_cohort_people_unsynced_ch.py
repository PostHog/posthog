from django.core.management.base import BaseCommand
from django.db import connections

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.models.cohort.cohort import Cohort

logger = structlog.get_logger(__name__)

BATCH_SIZE = 10000
PROD_US_CUTOFF = "2025-10-01 00:00:00"


class Command(BaseCommand):
    help = (
        "Sync cohort people records from ClickHouse person_static_cohort table to PostgreSQL posthog_cohortpeople table"
    )

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
            last_timestamp = start_date
            last_person_id = None
            last_cohort_id = 0
            first_batch = True

            while True:
                # Use keyset pagination for better performance
                if first_batch:
                    batch_query = """
                        SELECT DISTINCT person_id, cohort_id, team_id, _timestamp
                        FROM person_static_cohort
                        WHERE _timestamp >= %(cutoff_timestamp)s
                        ORDER BY _timestamp, person_id, cohort_id
                        LIMIT %(batch_size)s
                    """
                    params = {
                        "cutoff_timestamp": start_date,
                        "batch_size": batch_size,
                    }
                else:
                    batch_query = """
                        SELECT DISTINCT person_id, cohort_id, team_id, _timestamp
                        FROM person_static_cohort
                        WHERE (_timestamp > %(last_timestamp)s)
                           OR (_timestamp = %(last_timestamp)s AND person_id > %(last_person_id)s)
                           OR (_timestamp = %(last_timestamp)s AND person_id = %(last_person_id)s AND cohort_id > %(last_cohort_id)s)
                        ORDER BY _timestamp, person_id, cohort_id
                        LIMIT %(batch_size)s
                    """
                    params = {
                        "last_timestamp": last_timestamp,
                        "last_person_id": last_person_id,
                        "last_cohort_id": last_cohort_id,
                        "batch_size": batch_size,
                    }

                clickhouse_batch = sync_execute(batch_query, params)
                first_batch = False

                if not clickhouse_batch:
                    break

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Processing ClickHouse batch: {len(clickhouse_batch)} records (last: {last_timestamp})"
                    )
                )

                # Extract unique person UUIDs from this batch
                ch_person_uuids = list({str(record[0]) for record in clickhouse_batch})

                if not ch_person_uuids:
                    # Update keyset pagination cursor even if no UUIDs found
                    last_record = clickhouse_batch[-1]
                    last_timestamp = last_record[3]
                    last_person_id = str(last_record[0])
                    last_cohort_id = last_record[1]
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
                    self.stdout.write(f"No matching persons found for batch")
                    # Update keyset pagination cursor
                    last_record = clickhouse_batch[-1]
                    last_timestamp = last_record[3]
                    last_person_id = str(last_record[0])
                    last_cohort_id = last_record[1]
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

                insert_values = []
                for person_uuid, cohort_ids in cohort_data.items():
                    if person_uuid not in person_uuid_to_id:
                        continue
                    person_id = person_uuid_to_id[person_uuid]
                    for cohort_id in cohort_ids:
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
                        # Group by cohort_id and collect person UUIDs
                        person_id_to_uuid = {pid: uuid for uuid, pid in person_uuid_to_id.items()}
                        cohort_to_uuids: dict[int, list[str]] = {}
                        for cohort_id, person_id in insert_values:
                            uuid = person_id_to_uuid.get(person_id)

                            if uuid is not None:
                                if cohort_id not in cohort_to_uuids:
                                    cohort_to_uuids[cohort_id] = []
                                cohort_to_uuids[cohort_id].append(uuid)

                        batch_inserted = 0

                        for cohort_id, person_uuids in cohort_to_uuids.items():
                            try:
                                cohort = Cohort.objects.get(id=cohort_id)
                                cohort.insert_users_list_by_uuid_into_pg_only(
                                    items=person_uuids, team_id=cohort.team_id
                                )
                                batch_inserted += len(person_uuids)
                            except Exception as e:
                                self.stdout.write(self.style.ERROR(f"Error inserting into cohort {cohort_id}: {e}"))

                        total_inserted += batch_inserted

                        # Only track cohorts that actually had records inserted
                        if batch_inserted > 0:
                            cohorts_in_batch = set(cohort_to_uuids.keys())
                            cohorts_with_insertions.update(cohorts_in_batch)

                        self.stdout.write(self.style.SUCCESS(f"Batch successful: {batch_inserted} records inserted"))
                else:
                    self.stdout.write(f"No new records to insert for batch")

                # Update keyset pagination cursor to last record in batch
                last_record = clickhouse_batch[-1]
                last_timestamp = last_record[3]
                last_person_id = str(last_record[0])
                last_cohort_id = last_record[1]

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
