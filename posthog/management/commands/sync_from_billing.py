from django.core.management.base import BaseCommand

from posthog.models import Organization
from posthog.tasks.sync_billing import sync_from_billing


class Command(BaseCommand):
    help = "Sync latest from billing"

    def add_arguments(self, parser):
        parser.add_argument("--organization-ids", type=str, help="Comma separated list of organization ids to sync")
        parser.add_argument("--async", type=bool, help="Run the task asynchronously")
        parser.add_argument("--limit", type=int, help="Limit the number of organizations to sync")

    def handle(self, *args, **options):
        organization_ids = options["organization_ids"]
        run_async = options["async"]
        limit = options["limit"]

        if organization_ids:
            organizations = Organization.objects.filter(id__in=organization_ids.split(","))
        else:
            organizations = Organization.objects.all()

        if limit:
            organizations = organizations[:limit]

        print(f"Running sync for {len(organizations)} organizations")  # noqa T201

        for index, organization in enumerate(organizations):
            if run_async:
                sync_from_billing.delay(organization.id)
            else:
                sync_from_billing(organization.id)

                if index % 50 == 0:
                    print(f"Processed {index} organizations out of {len(organizations)}")  # noqa T201

        print("Done")  # noqa T201
