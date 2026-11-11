import csv
from contextlib import ExitStack
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management import BaseCommand, CommandParser

from posthog.models.organization import Organization

from ee.billing.billing_manager import BillingManager, BillingServiceResponseError, get_most_recent_owner

PROGRESS_EVERY = 100


def sync_organization(org_id: str) -> str | None:
    """Syncs one organization's members to billing. Returns why it failed, or None when billing accepted it."""
    try:
        return _sync_organization(org_id)
    except BillingServiceResponseError as e:
        return f"billing returned {e.status_code}"
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def _sync_organization(org_id: str) -> str | None:
    try:
        organization = Organization.objects.get(id=org_id)
    except (Organization.DoesNotExist, ValidationError):
        return "organization not found"

    owner = get_most_recent_owner(organization)
    if owner is None:
        return "organization has no owner"

    response = BillingManager(license=None, user=owner).sync_organization_users(organization)
    if not 200 <= response.status_code < 300:
        return f"billing returned {response.status_code}"
    return None


class Command(BaseCommand):
    help = (
        "Sync organization members to billing for each org_id in a CSV file. "
        "Run it away from billing's 03:45 UTC usage run, since each synced org with a subscription queues a usage sync."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("csv_file", type=str, help="CSV file with an org_id column")
        parser.add_argument("--offset", type=int, default=0, help="Skip this many rows of the CSV")
        parser.add_argument(
            "--failed-csv",
            type=str,
            default=None,
            help="Also write failed org_id,reason rows to this path. It can be passed back in as csv_file.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        with open(options["csv_file"], encoding="utf-8") as f:
            org_ids = [row["org_id"] for row in csv.DictReader(f)][options["offset"] :]

        total = len(org_ids)
        failed_org_ids: list[str] = []
        self.stdout.write(f"Syncing {total} organizations with billing")

        with ExitStack() as stack:
            failed_file = (
                stack.enter_context(open(options["failed_csv"], "w", encoding="utf-8", newline=""))
                if options["failed_csv"]
                else None
            )
            failed_writer = csv.writer(failed_file) if failed_file else None
            if failed_writer:
                failed_writer.writerow(["org_id", "reason"])

            for done, org_id in enumerate(org_ids, start=1):
                reason = sync_organization(org_id)
                if reason is not None:
                    failed_org_ids.append(org_id)
                    self.stderr.write(f"FAILED {org_id}: {reason}")
                    if failed_file and failed_writer:
                        failed_writer.writerow([org_id, reason])
                        failed_file.flush()

                if done % PROGRESS_EVERY == 0:
                    self.stdout.write(f"Progress: {done}/{total} ({len(failed_org_ids)} failed)")

        self.stdout.write(f"Finished: {total - len(failed_org_ids)} ok, {len(failed_org_ids)} failed")
        if failed_org_ids:
            self.stdout.write(f"Failed org ids: {', '.join(failed_org_ids)}")
