from django.core.management.base import BaseCommand
from django.utils import timezone

import structlog

from posthog.models.sharing_configuration import SharingConfiguration

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Clean up expired sharing configurations"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

    def handle(self, *args, **options):
        now = timezone.now()

        # Find expired configurations
        expired_configs = SharingConfiguration.objects.filter(expires_at__lt=now)

        count = expired_configs.count()

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(f"DRY RUN: Would delete {count} expired sharing configurations"))
            return

        if count == 0:
            self.stdout.write(self.style.SUCCESS("No expired sharing configurations to clean up"))
            return

        # Delete expired configurations
        deleted_count, _ = expired_configs.delete()

        logger.info("sharing_configs_cleanup_completed", deleted_count=deleted_count, timestamp=now.isoformat())

        self.stdout.write(self.style.SUCCESS(f"Successfully deleted {deleted_count} expired sharing configurations"))
