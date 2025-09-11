import logging

from django.core.management.base import BaseCommand

import structlog

from posthog.tasks.sync_all_organization_available_product_features import (
    sync_all_organization_available_product_features,
)

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Sync available features for all organizations"

    def handle(self, *args, **options):
        sync_all_organization_available_product_features()
        logger.info("Features synced for all organizations")
