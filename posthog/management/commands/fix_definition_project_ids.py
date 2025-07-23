from django.core.management.base import BaseCommand
from django.db import transaction, models
from posthog.models import EventDefinition, PropertyDefinition


class Command(BaseCommand):
    help = "Fix project_id alignment for EventDefinition and PropertyDefinition records where team.project_id != definition.project_id"

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

        self.stdout.write(self.style.SUCCESS("Starting definition project_id alignment process"))

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

            # Summary
            self.print_summary(event_def_stats, property_def_stats)

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

        misaligned_count = misaligned_query.count()

        if misaligned_count == 0:
            self.stdout.write(self.style.SUCCESS("✓ No EventDefinitions need project_id alignment"))
            return {"total": 0, "updated": 0}

        self.stdout.write(f"Found {misaligned_count} EventDefinitions with misaligned project_id")

        if self.dry_run:
            # Show sample of what would be updated
            sample_size = min(5, misaligned_count)
            sample_records = misaligned_query[:sample_size]

            for event_def in sample_records:
                self.stdout.write(
                    f"  Would update EventDefinition id={event_def.id} name='{event_def.name}' "
                    f"from project_id={event_def.project_id} to project_id={event_def.team.project_id}"
                )

            if sample_size < misaligned_count:
                self.stdout.write(f"  ... and {misaligned_count - sample_size} more EventDefinitions")

            return {"total": misaligned_count, "updated": 0}

        # Perform the update in batches to handle large datasets efficiently
        updated_count = 0

        # Simple but effective approach: process all records, updating in batches
        all_misaligned_ids = list(misaligned_query.values_list("id", flat=True))

        for i in range(0, len(all_misaligned_ids), self.batch_size):
            batch_ids = all_misaligned_ids[i : i + self.batch_size]
            batch_records = EventDefinition.objects.filter(id__in=batch_ids).select_related("team")

            with transaction.atomic():
                for event_def in batch_records:
                    event_def.project_id = event_def.team.project_id
                    event_def.save(update_fields=["project_id"])
                    updated_count += 1

            if i + self.batch_size < len(all_misaligned_ids):
                self.stdout.write(
                    f"  Processed {min(i + self.batch_size, len(all_misaligned_ids))}/{len(all_misaligned_ids)} EventDefinitions..."
                )

        self.stdout.write(self.style.SUCCESS(f"✓ Updated {updated_count} EventDefinitions"))

        return {"total": misaligned_count, "updated": updated_count}

    def process_property_definitions(self):
        """Process PropertyDefinition records that need project_id alignment."""

        # Find misaligned PropertyDefinitions
        misaligned_query = PropertyDefinition.objects.select_related("team").exclude(
            project_id=models.F("team__project_id")
        )

        misaligned_count = misaligned_query.count()

        if misaligned_count == 0:
            self.stdout.write(self.style.SUCCESS("✓ No PropertyDefinitions need project_id alignment"))
            return {"total": 0, "updated": 0}

        self.stdout.write(f"Found {misaligned_count} PropertyDefinitions with misaligned project_id")

        if self.dry_run:
            # Show sample of what would be updated
            sample_size = min(5, misaligned_count)
            sample_records = misaligned_query[:sample_size]

            for property_def in sample_records:
                self.stdout.write(
                    f"  Would update PropertyDefinition id={property_def.id} name='{property_def.name}' type={property_def.get_type_display()} "
                    f"from project_id={property_def.project_id} to project_id={property_def.team.project_id}"
                )

            if sample_size < misaligned_count:
                self.stdout.write(f"  ... and {misaligned_count - sample_size} more PropertyDefinitions")

            return {"total": misaligned_count, "updated": 0}

        # Perform the update in batches to handle large datasets efficiently
        updated_count = 0

        # Simple but effective approach: process all records, updating in batches
        all_misaligned_ids = list(misaligned_query.values_list("id", flat=True))

        for i in range(0, len(all_misaligned_ids), self.batch_size):
            batch_ids = all_misaligned_ids[i : i + self.batch_size]
            batch_records = PropertyDefinition.objects.filter(id__in=batch_ids).select_related("team")

            with transaction.atomic():
                for property_def in batch_records:
                    property_def.project_id = property_def.team.project_id
                    property_def.save(update_fields=["project_id"])
                    updated_count += 1

            if i + self.batch_size < len(all_misaligned_ids):
                self.stdout.write(
                    f"  Processed {min(i + self.batch_size, len(all_misaligned_ids))}/{len(all_misaligned_ids)} PropertyDefinitions..."
                )

        self.stdout.write(self.style.SUCCESS(f"✓ Updated {updated_count} PropertyDefinitions"))

        return {"total": misaligned_count, "updated": updated_count}

    def print_summary(self, event_def_stats, property_def_stats):
        """Print summary of changes made or that would be made."""

        total_found = event_def_stats["total"] + property_def_stats["total"]
        total_updated = event_def_stats["updated"] + property_def_stats["updated"]

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("SUMMARY")
        self.stdout.write("=" * 50)

        if self.dry_run:
            self.stdout.write(f"Total definitions found with misaligned project_id: {total_found}")
            self.stdout.write(f"  - EventDefinitions: {event_def_stats['total']}")
            self.stdout.write(f"  - PropertyDefinitions: {property_def_stats['total']}")
            self.stdout.write("\nNo changes were made (dry run mode)")

            if total_found > 0:
                self.stdout.write(f"\nRun without --dry-run to fix {total_found} misaligned records")
        else:
            self.stdout.write(f"Total definitions updated: {total_updated}")
            self.stdout.write(f"  - EventDefinitions: {event_def_stats['updated']}")
            self.stdout.write(f"  - PropertyDefinitions: {property_def_stats['updated']}")

            if total_updated > 0:
                self.stdout.write(self.style.SUCCESS(f"\n✓ Successfully aligned {total_updated} definition records"))
            else:
                self.stdout.write(self.style.SUCCESS("\n✓ All definition records were already aligned"))
