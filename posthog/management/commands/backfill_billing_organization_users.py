import csv

from django.core.management import BaseCommand

import structlog

from posthog.models.organization import Organization, OrganizationMembership

from ee.billing.billing_manager import BillingManager

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    """
    Used to sync organization_users with billing
    """

    def add_arguments(self, parser):
        parser.add_argument("csv_file", type=str)
        parser.add_argument("--offset", type=int, default=0)

    def handle(self, *args, **options):
        with open(options["csv_file"], encoding="utf-8") as f:
            reader = csv.DictReader(f)

            entries = list(reader)[options["offset"] :]
            total_count = len(entries)
            completed_count = 0
            failed_count = 0
            failed_org_ids = []

            logger.info(f"Total Backfill Entries: {total_count}")

            for row in entries:
                org_id = row["org_id"]
                try:
                    org = Organization.objects.get(id=org_id)

                    owner = (
                        OrganizationMembership.objects.filter(  # type: ignore
                            organization=org, level=OrganizationMembership.Level.OWNER
                        )
                        .first()
                        .user
                    )

                    billing_manager = BillingManager(license=None, user=owner)

                    try:
                        billing_manager.update_billing_organization_users(org)
                    except Exception as e:
                        logger.exception(f"Failed calling update_billing_organization_users: {e}")
                        raise

                    completed_count += 1
                except Exception:
                    failed_count += 1
                    failed_org_ids.append(org_id)

                logger.info(f"{completed_count}/{total_count} ({failed_count} failed)")

            logger.info(f"Finished backfilling {total_count} organizations")

            if failed_org_ids:
                logger.info(f"Failed updating {failed_org_ids}")
