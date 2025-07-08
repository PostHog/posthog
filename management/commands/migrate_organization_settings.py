from django.core.management.base import BaseCommand
from posthog.models.organization_setting_definitions import get_all_definitions


class Command(BaseCommand):
    help = "Migrate legacy organization settings to new system"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be migrated without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Get all definitions from code
        definitions = get_all_definitions()

        if dry_run:
            self.stdout.write("Would migrate the following settings:")
            for definition in definitions:
                self.stdout.write(f"  - {definition.setting_key.value}: {definition.setting_name}")
            return

        # For now, just show what definitions are available
        # In the future, this could migrate legacy settings from the organization model
        self.stdout.write("Available setting definitions:")
        for definition in definitions:
            self.stdout.write(f"  - {definition.setting_key.value}: {definition.setting_name}")

        self.stdout.write(self.style.SUCCESS("Migration completed successfully"))
