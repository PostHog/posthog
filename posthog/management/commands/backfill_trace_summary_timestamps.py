"""
Management command to backfill trace_timestamp for existing $ai_trace_summary events.

This creates new summary events with the trace_timestamp field populated,
which will supersede the old events when queried with argMax(..., timestamp).

Usage:
    python manage.py backfill_trace_summary_timestamps --team-id=1 --dry-run
    python manage.py backfill_trace_summary_timestamps --team-id=1
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

from django.core.management.base import BaseCommand

from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team


class Command(BaseCommand):
    help = "Backfill trace_timestamp for existing $ai_trace_summary events"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to backfill summaries for",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be done without making changes",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=1000,
            help="Maximum number of summaries to backfill (default: 1000)",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        dry_run = options["dry_run"]
        limit = options["limit"]

        self.stdout.write(f"Backfilling trace_timestamp for team {team_id}...")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        # Verify team exists
        try:
            Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Team {team_id} not found"))
            return

        # Query summary events missing trace_timestamp, joined with trace first event timestamps
        query = """
            SELECT
                s.uuid,
                s.trace_id,
                s.properties,
                s.distinct_id,
                t.first_event_ts
            FROM (
                SELECT
                    uuid,
                    JSONExtractString(properties, '$ai_trace_id') as trace_id,
                    properties,
                    distinct_id
                FROM events
                WHERE team_id = %(team_id)s
                    AND event = '$ai_trace_summary'
                    AND length(JSONExtractString(properties, 'trace_timestamp')) = 0
                ORDER BY timestamp DESC
                LIMIT %(limit)s
            ) s
            LEFT JOIN (
                SELECT
                    JSONExtractString(properties, '$ai_trace_id') as trace_id,
                    min(timestamp) as first_event_ts
                FROM events
                WHERE team_id = %(team_id)s
                    AND event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
                GROUP BY trace_id
            ) t ON s.trace_id = t.trace_id
            WHERE t.first_event_ts IS NOT NULL
        """

        results = sync_execute(query, {"team_id": team_id, "limit": limit})

        self.stdout.write(f"Found {len(results)} summary events to backfill")

        if not results:
            self.stdout.write(self.style.SUCCESS("No summaries need backfilling"))
            return

        # Process each summary
        created_count = 0
        skipped_count = 0

        # Prepare batch insert data
        events_to_insert = []

        for row in results:
            original_uuid, trace_id, properties_str, distinct_id, first_event_ts = row

            try:
                properties = json.loads(properties_str)
            except json.JSONDecodeError:
                self.stdout.write(self.style.WARNING(f"  Skipping {trace_id}: invalid JSON properties"))
                skipped_count += 1
                continue

            # Add trace_timestamp
            trace_timestamp = first_event_ts.isoformat() if first_event_ts else ""
            properties["trace_timestamp"] = trace_timestamp

            if dry_run:
                self.stdout.write(f"  Would create new summary for {trace_id} with trace_timestamp={trace_timestamp}")
            else:
                # Prepare event data for batch insert
                now = datetime.now(tz=UTC)
                events_to_insert.append(
                    (
                        str(uuid4()),  # uuid
                        "$ai_trace_summary",  # event
                        json.dumps(properties),  # properties
                        now,  # timestamp
                        team_id,  # team_id
                        distinct_id,  # distinct_id
                        "",  # elements_chain
                        now,  # created_at
                    )
                )
                self.stdout.write(f"  Prepared new summary for {trace_id} with trace_timestamp={trace_timestamp}")

            created_count += 1

        # Batch insert events directly into ClickHouse via writable_events
        if not dry_run and events_to_insert:
            insert_query = """
                INSERT INTO writable_events (
                    uuid,
                    event,
                    properties,
                    timestamp,
                    team_id,
                    distinct_id,
                    elements_chain,
                    created_at
                ) VALUES
            """
            sync_execute(
                insert_query,
                events_to_insert,
                settings={"max_execution_time": 300},
            )
            self.stdout.write(f"  Inserted {len(events_to_insert)} events into ClickHouse")

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"DRY RUN complete: would create {created_count} events, skip {skipped_count}")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Backfill complete: created {created_count} events, skipped {skipped_count}")
            )
