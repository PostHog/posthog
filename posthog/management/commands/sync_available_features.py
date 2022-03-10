import structlog
from django.core.management.base import BaseCommand

from posthog.celery import sync_all_organization_available_features

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Sync available features for all organizations"

    def handle(self, *args, **options):
        sync_all_organization_available_features()
        logger.info(f"Features synced for all organizations")
