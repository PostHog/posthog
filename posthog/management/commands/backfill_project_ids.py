import time

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Backfill project_id in action tables from posthog_team.project_id in batches"

    def add_arguments(self, parser):
        parser.add_argument("--table-name", type=str, required=True, help="Name of the table to update (required)")
        parser.add_argument("--batch-size", type=int, default=1000, help="Number of rows to update in each batch")
        parser.add_argument("--sleep-interval", type=float, default=0.5, help="Sleep time between batches in seconds")
        parser.add_argument("--dry-run", action="store_true", help="Run without making any changes")
        parser.add_argument(
            "--max-batches", type=int, default=None, help="Maximum number of batches to process (None = unlimited)"
        )

    def handle(self, *args, **options):
        self.table_name = options["table_name"]
        self.team_table = "posthog_team"  # Fixed to posthog_team

        try:
            self.stdout.write(self.style.SUCCESS("Starting project_id update process"))
            self.stdout.write(
                f"Configuration: table={self.table_name}, "
                f"batch_size={options['batch_size']}, sleep_interval={options['sleep_interval']}, "
                f"dry_run={options['dry_run']}, max_batches={options['max_batches']}"
            )

            self.update_with_sql(options)

            self.stdout.write(self.style.SUCCESS("Process completed successfully"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error occurred: {e}"))

    def get_total_records(self):
        """Get total count of records needing updates."""
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {self.table_name} WHERE project_id IS NULL")
            count = cursor.fetchone()[0]

        self.stdout.write(f"Found {count} records with NULL project_id in {self.table_name}")
        return count

    def update_with_sql(self, options):
        """
        Update project_id from posthog_team.project_id in batches using PostgreSQL-optimized SQL.
        """
        total_updated = 0
        batch_count = 0
        batch_size = options["batch_size"]

        # Get initial count
        total_to_update = self.get_total_records()

        if total_to_update == 0:
            self.stdout.write(self.style.SUCCESS("No records to update. Exiting."))
            return

        # Log start time for performance monitoring
        start_time = time.time()

        while True:
            batch_start_time = time.time()

            # Use SQL to update a batch
            with connection.cursor() as cursor:
                if options["dry_run"]:
                    # In dry run, just select the rows that would be updated
                    cursor.execute(f"""
                        SELECT a.id, t.project_id
                        FROM {self.table_name} a
                        JOIN {self.team_table} t ON a.team_id = t.id
                        WHERE a.project_id IS NULL
                        LIMIT {batch_size}
                    """)
                    rows = cursor.fetchall()
                    update_count = len(rows)

                    # Log sample of rows that would be updated (to avoid console spam)
                    sample_size = min(5, update_count)
                    for row in rows[:sample_size]:
                        self.stdout.write(
                            f"DRY RUN: Would update {self.table_name} id={row[0]} with project_id={row[1]}"
                        )

                    if sample_size < update_count:
                        self.stdout.write(f"DRY RUN: ... and {update_count - sample_size} more rows")
                else:
                    # Use PostgreSQL's efficient UPDATE FROM syntax with RETURNING
                    cursor.execute(f"""
                        WITH updated_rows AS (
                            UPDATE {self.table_name} a
                            SET project_id = t.project_id
                            FROM {self.team_table} t
                            WHERE a.team_id = t.id
                            AND a.project_id IS NULL
                            AND a.id IN (
                                SELECT a.id
                                FROM {self.table_name} a
                                JOIN {self.team_table} t ON a.team_id = t.id
                                WHERE a.project_id IS NULL
                                LIMIT {batch_size}
                            )
                            RETURNING a.id
                        )
                        SELECT COUNT(*) FROM updated_rows
                    """)
                    update_count = cursor.fetchone()[0]

            batch_duration = time.time() - batch_start_time

            if update_count == 0:
                self.stdout.write(self.style.SUCCESS("No more records to update. Exiting."))
                break

            total_updated += update_count
            batch_count += 1

            # Calculate metrics
            progress = (total_updated / total_to_update) * 100 if total_to_update > 0 else 100
            elapsed_time = time.time() - start_time
            estimated_remaining = (
                (elapsed_time / total_updated) * (total_to_update - total_updated) if total_updated > 0 else 0
            )

            # Report on this batch
            if not options["dry_run"]:
                self.stdout.write(
                    f"Batch {batch_count}: Updated {update_count} records in {batch_duration:.2f}s "
                    f"({update_count/batch_duration:.1f} rows/sec)"
                )
            else:
                self.stdout.write(f"Batch {batch_count}: Would have updated {update_count} records (dry run)")

            # Report overall progress
            self.stdout.write(
                f"Progress: {progress:.2f}% ({total_updated}/{total_to_update}) | "
                f"Elapsed: {elapsed_time:.1f}s | "
                f"Estimated remaining: {estimated_remaining:.1f}s"
            )

            # Break after first iteration if in dry run mode
            if options["dry_run"]:
                self.stdout.write(self.style.SUCCESS("Dry run completed after first batch. Exiting."))
                break

            # Check if we've reached max_batches
            if options["max_batches"] and batch_count >= options["max_batches"]:
                self.stdout.write(f"Reached maximum batch count of {options['max_batches']}. Stopping.")
                break

            # Sleep between batches to reduce database load
            time.sleep(options["sleep_interval"])

        # Final summary
        total_duration = time.time() - start_time
        avg_speed = total_updated / total_duration if total_duration > 0 else 0

        self.stdout.write(
            self.style.SUCCESS(
                f"Completed update. Total records updated: {total_updated} in {total_duration:.1f}s "
                f"({avg_speed:.1f} rows/sec)"
            )
        )
