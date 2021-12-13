import structlog
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand
from semantic_version.base import Version

from posthog.models.special_migration import MigrationStatus, SpecialMigration
from posthog.special_migrations.runner import start_special_migration
from posthog.special_migrations.setup import ALL_SPECIAL_MIGRATIONS, POSTHOG_VERSION, setup_special_migrations

logger = structlog.get_logger(__name__)


def get_necessary_migrations():
    necessary_migrations = []
    for migration_name, definition in ALL_SPECIAL_MIGRATIONS.items():
        sm = SpecialMigration.objects.get_or_create(
            name=migration_name,
            description=definition.description,
            posthog_min_version=definition.posthog_min_version,
            posthog_max_version=definition.posthog_max_version,
        )[0]
        if POSTHOG_VERSION > Version(sm.posthog_max_version) and ALL_SPECIAL_MIGRATIONS[migration_name].is_required():
            necessary_migrations.append(sm)

    return necessary_migrations


class Command(BaseCommand):
    help = "Run special migrations"

    def add_arguments(self, parser):
        parser.add_argument(
            "--plan", action="store_true", help="Show the special migrations that will run",
        )

    def handle(self, *args, **options):

        setup_special_migrations(ignore_posthog_version=True)
        necessary_migrations = get_necessary_migrations()

        if options["plan"]:
            print()

            if len(necessary_migrations) == 0:
                print("Special migrations up to date!")
                return

            print("List of special migrations to be applied:")

            for migration in necessary_migrations:
                print(f"- {migration.name}")

            print()
            return

        for migration in necessary_migrations:
            logger.info(f"Applying special migration {migration.name}")
            started_successfully = start_special_migration(migration.name, ignore_posthog_version=True)
            migration.refresh_from_db()
            if not started_successfully or migration.status != MigrationStatus.CompletedSuccessfully:
                logger.info(f"Unable to complete special migration {migration.name} with error: {migration.last_error}")
                raise ImproperlyConfigured(
                    f"Migrate job failed because necessary special migration {migration.name} could not complete."
                )

            logger.info(f"✅ Migration {migration.name} successful")
