from django.core.management.base import BaseCommand

from posthog.models import Organization


class Command(BaseCommand):
    help = "Sync available features for all organizations"

    def handle(self, *args, **options):
        for org in Organization.objects.all():
            org.update_available_features()
            org.save()
            billing_plan, _ = org._billing_plan_details
            print(f"{billing_plan} features synced for org: {org.name}")
