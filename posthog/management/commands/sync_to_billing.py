from django.core.management.base import BaseCommand

from posthog.models import Organization, OrganizationMembership


class Command(BaseCommand):
    help = "Run a sync to billing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--action",
            type=str,
            help="Select the action to perform, 'distinct_ids', 'admin_emails' or 'customer_email'",
        )
        parser.add_argument("--organization-ids", type=str, help="Comma separated list of organization ids to sync")

    def handle(self, *args, **options):
        action = options["action"]
        organization_ids = options["organization_ids"]

        if action not in ["organization_users"]:
            print("Invalid action, please select 'distinct_ids', 'admin_emails' or 'customer_email'")  # noqa T201
            return

        if organization_ids:
            organizations = Organization.objects.filter(id__in=organization_ids.split(","))
        else:
            organizations = Organization.objects.all()

        print(f"Running {action} for {len(organizations)} organizations")  # noqa T201

        for index, organization in enumerate(organizations):
            first_owner = organization.members.filter(
                organization_membership__level__gte=OrganizationMembership.Level.OWNER
            ).first()
            if not first_owner:
                print(f"Organization {organization.id} has no owner")  # noqa T201

            if action == "organization_users":
                first_owner.update_billing_organization_users(organization)

            if index % 50 == 0:
                print(f"Processed {index} organizations out of {len(organizations)}")  # noqa T201

        print("Done")  # noqa T201
