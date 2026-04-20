"""
Management command to create test data for sync_person_distinct_ids workflow.

Creates orphaned persons in ClickHouse with various scenarios:
- Fixable: Person in CH + PG, DID only in PG (should be synced)
- Truly orphaned: Person in CH + PG, no DID anywhere (report only)
- CH-only orphan: Person only in CH (should be marked deleted)

Usage:
    python manage.py setup_orphan_test_data --team-id 1
    python manage.py setup_orphan_test_data --team-id 1 --fixable 5 --truly-orphaned 3 --ch-only 2
    python manage.py setup_orphan_test_data --team-id 1 --cleanup  # Remove test data
"""

import uuid

from django.core.management.base import BaseCommand

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import Team
from posthog.models.person import Person, PersonDistinctId
from posthog.person_db_router import PERSONS_DB_FOR_WRITE


class Command(BaseCommand):
    help = "Create test data for sync_person_distinct_ids workflow"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to create test data for",
        )
        parser.add_argument(
            "--fixable",
            type=int,
            default=3,
            help="Number of fixable orphans (person in CH+PG, DID only in PG)",
        )
        parser.add_argument(
            "--truly-orphaned",
            type=int,
            default=2,
            help="Number of truly orphaned (person in CH+PG, no DID anywhere)",
        )
        parser.add_argument(
            "--ch-only",
            type=int,
            default=2,
            help="Number of CH-only orphans (person only in CH, not in PG)",
        )
        parser.add_argument(
            "--cleanup",
            action="store_true",
            help="Remove test data instead of creating it",
        )
        parser.add_argument(
            "--prefix",
            type=str,
            default="test-orphan",
            help="Prefix for test distinct IDs (default: test-orphan)",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        prefix = options["prefix"]

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Team {team_id} does not exist"))
            return

        if options["cleanup"]:
            self.cleanup_test_data(team, prefix)
        else:
            self.create_test_data(
                team=team,
                prefix=prefix,
                fixable_count=options["fixable"],
                truly_orphaned_count=options["truly_orphaned"],
                ch_only_count=options["ch_only"],
            )

    def create_test_data(
        self,
        team: Team,
        prefix: str,
        fixable_count: int,
        truly_orphaned_count: int,
        ch_only_count: int,
    ):
        self.stdout.write(f"\nCreating test orphan data for team {team.id}...")
        self.stdout.write(f"  Fixable orphans: {fixable_count}")
        self.stdout.write(f"  Truly orphaned: {truly_orphaned_count}")
        self.stdout.write(f"  CH-only orphans: {ch_only_count}")

        created_persons: list[tuple[str, str, str | None]] = []

        # 1. Fixable orphans: Person in CH + PG, DID only in PG
        self.stdout.write(self.style.WARNING("\n[Fixable Orphans]"))
        for i in range(fixable_count):
            person_uuid = str(uuid.uuid4())
            distinct_id = f"{prefix}-fixable-{i}-{person_uuid[:8]}"

            # Create person in PostgreSQL with distinct ID
            person = Person.objects.db_manager(PERSONS_DB_FOR_WRITE).create(
                team=team,
                uuid=person_uuid,
                properties={"test_type": "fixable", "index": i},
            )
            PersonDistinctId.objects.db_manager(PERSONS_DB_FOR_WRITE).create(
                team=team,
                person=person,
                distinct_id=distinct_id,
                version=0,
            )

            # Create person in ClickHouse WITHOUT distinct ID
            self._insert_person_to_ch(team.id, person_uuid, version=0)
            # Deliberately NOT inserting distinct_id to CH

            created_persons.append(("fixable", person_uuid, distinct_id))
            self.stdout.write(f"  Created: {person_uuid[:8]}... -> {distinct_id}")

        # 2. Truly orphaned: Person in CH + PG, no DID anywhere
        self.stdout.write(self.style.WARNING("\n[Truly Orphaned]"))
        for i in range(truly_orphaned_count):
            person_uuid = str(uuid.uuid4())

            # Create person in PostgreSQL WITHOUT distinct ID
            Person.objects.db_manager(PERSONS_DB_FOR_WRITE).create(
                team=team,
                uuid=person_uuid,
                properties={"test_type": "truly_orphaned", "index": i},
            )

            # Create person in ClickHouse WITHOUT distinct ID
            self._insert_person_to_ch(team.id, person_uuid, version=0)

            created_persons.append(("truly_orphaned", person_uuid, None))
            self.stdout.write(f"  Created: {person_uuid[:8]}... (no DID)")

        # 3. CH-only orphans: Person only in CH, not in PG
        self.stdout.write(self.style.WARNING("\n[CH-Only Orphans]"))
        for _ in range(ch_only_count):
            person_uuid = str(uuid.uuid4())

            # Create person ONLY in ClickHouse
            self._insert_person_to_ch(team.id, person_uuid, version=0)
            # Deliberately NOT creating in PostgreSQL

            created_persons.append(("ch_only", person_uuid, None))
            self.stdout.write(f"  Created: {person_uuid[:8]}... (CH only)")

        # Summary
        self.stdout.write(self.style.SUCCESS(f"\n✓ Created {len(created_persons)} test orphans"))
        self.stdout.write("\nTo verify orphans exist, run:")
        self.stdout.write(
            f"  python manage.py start_temporal_workflow sync-person-distinct-ids '{{\"team_id\": {team.id}}}'"
        )

        self.stdout.write("\nTo clean up test data:")
        self.stdout.write(f"  python manage.py setup_orphan_test_data --team-id {team.id} --cleanup --prefix {prefix}")

    def cleanup_test_data(self, team: Team, prefix: str):
        self.stdout.write(f"\nCleaning up test data for team {team.id} with prefix '{prefix}'...")

        # Find test persons in PostgreSQL by properties
        pg_persons = Person.objects.db_manager(PERSONS_DB_FOR_WRITE).filter(
            team=team,
            properties__test_type__in=["fixable", "truly_orphaned"],
        )
        pg_uuids = list(pg_persons.values_list("uuid", flat=True))

        # Delete from PostgreSQL
        deleted_dids = (
            PersonDistinctId.objects.db_manager(PERSONS_DB_FOR_WRITE)
            .filter(
                team=team,
                distinct_id__startswith=prefix,
            )
            .delete()
        )
        deleted_persons = pg_persons.delete()

        self.stdout.write(f"  Deleted {deleted_persons[0]} persons from PostgreSQL")
        self.stdout.write(f"  Deleted {deleted_dids[0]} distinct IDs from PostgreSQL")

        # Mark as deleted in ClickHouse (we can't truly delete, but can mark is_deleted=1)
        if pg_uuids:
            sync_execute(
                """
                INSERT INTO person (id, team_id, is_deleted, version, _timestamp, _offset)
                SELECT id, team_id, 1, version + 100, now(), 0
                FROM person FINAL
                WHERE team_id = %(team_id)s AND id IN %(uuid_list)s
                """,
                {"team_id": team.id, "uuid_list": pg_uuids},
            )
            self.stdout.write(f"  Marked {len(pg_uuids)} persons as deleted in ClickHouse")

        # Also mark any CH-only orphans with test properties
        # (We can identify them by checking for properties.test_type which we didn't set for CH-only,
        # but we can still clean up based on recent creation or by running the workflow)

        self.stdout.write(self.style.SUCCESS("\n✓ Cleanup complete"))
        self.stdout.write("\nNote: CH-only orphans (without PG records) may still exist.")
        self.stdout.write("Run the workflow with delete_ch_only_orphans=true to clean them up:")
        self.stdout.write(
            f"  python manage.py start_temporal_workflow sync-person-distinct-ids "
            f'\'{{"team_id": {team.id}, "dry_run": false, "delete_ch_only_orphans": true, "categorize_orphans": true}}\''
        )

    def _insert_person_to_ch(self, team_id: int, person_uuid: str, version: int = 0):
        """Insert a person directly into ClickHouse person table."""
        sync_execute(
            """
            INSERT INTO person (id, team_id, properties, is_deleted, is_identified, version, _timestamp, _offset)
            VALUES (%(uuid)s, %(team_id)s, '{}', 0, 0, %(version)s, now(), 0)
            """,
            {
                "uuid": person_uuid,
                "team_id": team_id,
                "version": version,
            },
        )
