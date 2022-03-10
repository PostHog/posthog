import structlog
from django.core.management.base import BaseCommand

from posthog.models import Organization

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Sync available features for all organizations"

    def handle(self, *args, **options):
        for org in Organization.objects.all():
            org.update_available_features()
            org.save()
            billing_plan, _ = org._billing_plan_details
            logger.info(f"{billing_plan} features synced for org: {org.name}")
