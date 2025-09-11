from django.core.management.base import BaseCommand
from django.db import IntegrityError, models
from django.db.models import Count

from posthog.models import EventDefinition, GroupTypeMapping, PropertyDefinition
from posthog.storage.environments_rollback_storage import get_all_rollback_organization_ids


class Command(BaseCommand):
    help = "Fix project_id alignment for EventDefinition, PropertyDefinition, and GroupTypeMapping records where team.project_id != definition.project_id (only for organizations that have triggered environment rollback)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Run without making any changes, only show what would be updated"
        )
        parser.add_argument(
            "--batch-size", type=int, default=1000, help="Number of records to process in each batch (default: 1000)"
        )

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        self.batch_size = options["batch_size"]

        self.failed_records: dict[str, list[int]] = {
            "EventDefinition": [],
            "PropertyDefinition": [],
            "GroupTypeMapping": [],
        }

        self.stdout.write(self.style.SUCCESS("Starting definition project_id alignment process"))

        rollback_org_ids = get_all_rollback_organization_ids()
        if not rollback_org_ids:
            self.stdout.write(self.style.WARNING("No organizations have triggered environment rollback. Exiting."))
            return
        self.stdout.write(f"Processing only rolled back organizations: {len(rollback_org_ids)} orgs")
        # Organization IDs are UUIDs, not integers
        self.rollback_org_ids = rollback_org_ids

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))
        else:
            self.stdout.write(f"Batch size: {self.batch_size}")

        try:
            # Process EventDefinitions
            self.stdout.write("\n=== Processing EventDefinitions ===")
            event_def_stats = self.process_event_definitions()

            # Process PropertyDefinitions
            self.stdout.write("\n=== Processing PropertyDefinitions ===")
            property_def_stats = self.process_property_definitions()

            # Process GroupTypeMappings
            self.stdout.write("\n=== Processing GroupTypeMappings ===")
            group_type_mapping_stats = self.process_group_type_mappings()

            # Summary
            self.print_summary(event_def_stats, property_def_stats, group_type_mapping_stats)

            self.stdout.write(self.style.SUCCESS("Process completed successfully"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error occurred: {e}"))
            raise

    def process_event_definitions(self):
        """Process EventDefinition records that need project_id alignment."""

        # Find misaligned EventDefinitions
        misaligned_query = EventDefinition.objects.select_related("team").exclude(
            project_id=models.F("team__project_id")
        )

        # Filter by rollback organizations
        misaligned_query = misaligned_query.filter(team__organization_id__in=self.rollback_org_ids)

        misaligned_count = misaligned_query.count()

        if misaligned_count == 0:
            self.stdout.write(self.style.SUCCESS("✓ No EventDefinitions need project_id alignment"))
            return {"total": 0, "updated": 0}

        self.stdout.write(f"Found {misaligned_count} EventDefinitions with misaligned project_id")

        if self.dry_run:
            team_summary = (
                misaligned_query.values("team_id", "team__name", "team__organization_id", "team__organization__name")
                .annotate(count=Count("id"))
                .order_by("team__organization_id", "team_id")
            )

            current_org_id = None
            for entry in team_summary:
                if entry["team__organization_id"] != current_org_id:
                    current_org_id = entry["team__organization_id"]
                    self.stdout.write(f"\n  Organization: {entry['team__organization__name']} (ID: {current_org_id})")

                self.stdout.write(
                    f"    Team: {entry['team__name']} (ID: {entry['team_id']}) - "
                    f"{entry['count']} EventDefinitions to update"
                )

            return {"total": misaligned_count, "updated": 0}

        # Perform the update in batches to handle large datasets efficiently
        updated_count = 0

        # Simple but effective approach: process all records, updating in batches
        all_misaligned_ids = list(misaligned_query.values_list("id", flat=True))

        for i in range(0, len(all_misaligned_ids), self.batch_size):
            batch_ids = all_misaligned_ids[i : i + self.batch_size]
            batch_records = EventDefinition.objects.filter(id__in=batch_ids).select_related("team")

            for event_def in batch_records:
                event_def.project_id = event_def.team.project_id
                try:
                    event_def.save(update_fields=["project_id"])
                    updated_count += 1
                except IntegrityError:
                    self.failed_records["EventDefinition"].append(event_def.id)

            if i + self.batch_size < len(all_misaligned_ids):
                self.stdout.write(
                    f"  Processed {min(i + self.batch_size, len(all_misaligned_ids))}/{len(all_misaligned_ids)} EventDefinitions..."
                )

        self.stdout.write(self.style.SUCCESS(f"✓ Updated {updated_count} EventDefinitions"))

        failed_count = len(self.failed_records["EventDefinition"])
        if failed_count > 0:
            self.stdout.write(
                self.style.WARNING(f"⚠ Failed to update {failed_count} EventDefinitions due to integrity errors")
            )

        return {"total": misaligned_count, "updated": updated_count, "failed": failed_count}

    def process_property_definitions(self):
        """Process PropertyDefinition records that need project_id alignment."""

        # Find misaligned PropertyDefinitions
        misaligned_query = PropertyDefinition.objects.select_related("team").exclude(
            project_id=models.F("team__project_id")
        )

        # Filter by rollback organizations
        misaligned_query = misaligned_query.filter(team__organization_id__in=self.rollback_org_ids)

        misaligned_count = misaligned_query.count()

        if misaligned_count == 0:
            self.stdout.write(self.style.SUCCESS("✓ No PropertyDefinitions need project_id alignment"))
            return {"total": 0, "updated": 0}

        self.stdout.write(f"Found {misaligned_count} PropertyDefinitions with misaligned project_id")

        if self.dry_run:
            team_summary = (
                misaligned_query.values("team_id", "team__name", "team__organization_id", "team__organization__name")
                .annotate(count=Count("id"))
                .order_by("team__organization_id", "team_id")
            )

            current_org_id = None
            for entry in team_summary:
                if entry["team__organization_id"] != current_org_id:
                    current_org_id = entry["team__organization_id"]
                    self.stdout.write(f"\n  Organization: {entry['team__organization__name']} (ID: {current_org_id})")

                self.stdout.write(
                    f"    Team: {entry['team__name']} (ID: {entry['team_id']}) - "
                    f"{entry['count']} PropertyDefinitions to update"
                )

            return {"total": misaligned_count, "updated": 0}

        # Perform the update in batches to handle large datasets efficiently
        updated_count = 0

        # Simple but effective approach: process all records, updating in batches
        all_misaligned_ids = list(misaligned_query.values_list("id", flat=True))

        for i in range(0, len(all_misaligned_ids), self.batch_size):
            batch_ids = all_misaligned_ids[i : i + self.batch_size]
            batch_records = PropertyDefinition.objects.filter(id__in=batch_ids).select_related("team")

            for property_def in batch_records:
                property_def.project_id = property_def.team.project_id
                try:
                    property_def.save(update_fields=["project_id"])
                    updated_count += 1
                except IntegrityError:
                    self.failed_records["PropertyDefinition"].append(property_def.id)

            if i + self.batch_size < len(all_misaligned_ids):
                self.stdout.write(
                    f"  Processed {min(i + self.batch_size, len(all_misaligned_ids))}/{len(all_misaligned_ids)} PropertyDefinitions..."
                )

        self.stdout.write(self.style.SUCCESS(f"✓ Updated {updated_count} PropertyDefinitions"))

        failed_count = len(self.failed_records["PropertyDefinition"])
        if failed_count > 0:
            self.stdout.write(
                self.style.WARNING(f"⚠ Failed to update {failed_count} PropertyDefinitions due to integrity errors")
            )

        return {"total": misaligned_count, "updated": updated_count, "failed": failed_count}

    def process_group_type_mappings(self):
        """Process GroupTypeMapping records that need project_id alignment."""

        # Find misaligned GroupTypeMappings
        misaligned_query = GroupTypeMapping.objects.select_related("team").exclude(
            project_id=models.F("team__project_id")
        )

        # Filter by rollback organizations
        misaligned_query = misaligned_query.filter(team__organization_id__in=self.rollback_org_ids)

        misaligned_count = misaligned_query.count()

        if misaligned_count == 0:
            self.stdout.write(self.style.SUCCESS("✓ No GroupTypeMappings need project_id alignment"))
            return {"total": 0, "updated": 0}

        self.stdout.write(f"Found {misaligned_count} GroupTypeMappings with misaligned project_id")

        if self.dry_run:
            team_summary = (
                misaligned_query.values("team_id", "team__name", "team__organization_id", "team__organization__name")
                .annotate(count=Count("id"))
                .order_by("team__organization_id", "team_id")
            )

            current_org_id = None
            for entry in team_summary:
                if entry["team__organization_id"] != current_org_id:
                    current_org_id = entry["team__organization_id"]
                    self.stdout.write(f"\n  Organization: {entry['team__organization__name']} (ID: {current_org_id})")

                self.stdout.write(
                    f"    Team: {entry['team__name']} (ID: {entry['team_id']}) - "
                    f"{entry['count']} GroupTypeMappings to update"
                )

            return {"total": misaligned_count, "updated": 0}

        # Perform the update in batches to handle large datasets efficiently
        updated_count = 0

        # Simple but effective approach: process all records, updating in batches
        all_misaligned_ids = list(misaligned_query.values_list("id", flat=True))

        for i in range(0, len(all_misaligned_ids), self.batch_size):
            batch_ids = all_misaligned_ids[i : i + self.batch_size]
            batch_records = GroupTypeMapping.objects.filter(id__in=batch_ids).select_related("team")

            for group_type_mapping in batch_records:
                group_type_mapping.project_id = group_type_mapping.team.project_id
                try:
                    group_type_mapping.save(update_fields=["project_id"])
                    updated_count += 1
                except IntegrityError:
                    self.failed_records["GroupTypeMapping"].append(group_type_mapping.id)

            if i + self.batch_size < len(all_misaligned_ids):
                self.stdout.write(
                    f"  Processed {min(i + self.batch_size, len(all_misaligned_ids))}/{len(all_misaligned_ids)} GroupTypeMappings..."
                )

        self.stdout.write(self.style.SUCCESS(f"✓ Updated {updated_count} GroupTypeMappings"))

        failed_count = len(self.failed_records["GroupTypeMapping"])
        if failed_count > 0:
            self.stdout.write(
                self.style.WARNING(f"⚠ Failed to update {failed_count} GroupTypeMappings due to integrity errors")
            )

        return {"total": misaligned_count, "updated": updated_count, "failed": failed_count}

    def print_summary(self, event_def_stats, property_def_stats, group_type_mapping_stats):
        """Print summary of changes made or that would be made."""

        total_found = event_def_stats["total"] + property_def_stats["total"] + group_type_mapping_stats["total"]
        total_updated = event_def_stats["updated"] + property_def_stats["updated"] + group_type_mapping_stats["updated"]
        total_failed = (
            event_def_stats.get("failed", 0)
            + property_def_stats.get("failed", 0)
            + group_type_mapping_stats.get("failed", 0)
        )

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("SUMMARY")
        self.stdout.write("=" * 50)

        if self.dry_run:
            self.stdout.write(f"Total definitions found with misaligned project_id: {total_found}")
            self.stdout.write(f"  - EventDefinitions: {event_def_stats['total']}")
            self.stdout.write(f"  - PropertyDefinitions: {property_def_stats['total']}")
            self.stdout.write(f"  - GroupTypeMappings: {group_type_mapping_stats['total']}")
            self.stdout.write("\nNo changes were made (dry run mode)")

            if total_found > 0:
                self.stdout.write(f"\nRun without --dry-run to fix {total_found} misaligned records")
        else:
            self.stdout.write(f"Total definitions updated: {total_updated}")
            self.stdout.write(f"  - EventDefinitions: {event_def_stats['updated']}")
            self.stdout.write(f"  - PropertyDefinitions: {property_def_stats['updated']}")
            self.stdout.write(f"  - GroupTypeMappings: {group_type_mapping_stats['updated']}")

            if total_failed > 0:
                self.stdout.write(self.style.WARNING(f"\nTotal definitions failed: {total_failed}"))
                self.stdout.write(f"  - EventDefinitions: {event_def_stats.get('failed', 0)}")
                self.stdout.write(f"  - PropertyDefinitions: {property_def_stats.get('failed', 0)}")
                self.stdout.write(f"  - GroupTypeMappings: {group_type_mapping_stats.get('failed', 0)}")

                # Print failed record IDs
                if self.failed_records["EventDefinition"]:
                    self.stdout.write(f"\nFailed EventDefinition IDs: {self.failed_records['EventDefinition']}")
                if self.failed_records["PropertyDefinition"]:
                    self.stdout.write(f"Failed PropertyDefinition IDs: {self.failed_records['PropertyDefinition']}")
                if self.failed_records["GroupTypeMapping"]:
                    self.stdout.write(f"Failed GroupTypeMapping IDs: {self.failed_records['GroupTypeMapping']}")

            if total_updated > 0:
                self.stdout.write(self.style.SUCCESS(f"\n✓ Successfully aligned {total_updated} definition records"))
            else:
                self.stdout.write(self.style.SUCCESS("\n✓ All definition records were already aligned"))
