import logging
from collections.abc import Iterable

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.paginator import Paginator
from django.db.models import Q

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from posthog.models.integration import Integration

logger = logging.getLogger(__name__)


def _batched(iterable: Iterable, size: int) -> Iterable[list]:
    batch: list = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def migrate_ses_tenants(team_ids: list[int], domains: list[str], dry_run: bool = False):
    """
    Ensure existing SES email identities have SES Tenants and Tenant Resource Associations.

    The command is idempotent.
    """
    if team_ids and domains:
        print("Please provide either team_ids or domains, not both")  # noqa: T201
        return

    query = (
        Integration.objects.filter(kind="email")
        .filter(Q(config__provider="ses") | Q(config__provider__isnull=True))
        .order_by("id")
    )

    if team_ids:
        print("Setting up SES tenants for teams:", team_ids)  # noqa: T201
        query = query.filter(team_id__in=team_ids)
    elif domains:
        print("Setting up SES tenants for domains:", domains)  # noqa: T201
        # Domains are stored in Integration.config["domain"]
        query = query.filter(config__domain__in=domains)
    else:
        print("Setting up SES tenants for all SES email identities")  # noqa: T201

    # Collect unique (team_id, domain) pairs to avoid duplicate work per domain
    pairs: list[tuple[int, str]] = []
    paginator = Paginator(query, 200)

    for page_num in paginator.page_range:
        page = paginator.page(page_num)
        for integration in page.object_list:
            domain = integration.config.get("domain")
            if not domain:
                continue
            provider = integration.config.get("provider", "mailjet")
            if provider != "ses":
                continue
            pair = (integration.team_id, domain)
            if pair not in pairs:
                pairs.append(pair)

    if not pairs:
        print("No SES email identities found to migrate.")  # noqa: T201
        return

    sts_client = boto3.client(
        "sts",
    )
    tenant_client = boto3.client(
        "sesv2",
    )

    try:
        aws_account_id = sts_client.get_caller_identity()["Account"]
    except (ClientError, BotoCoreError) as e:
        logger.exception("Failed to get AWS account id for SES tenant association: %s", e)
        print("Error determining AWS account ID. Aborting.")  # noqa: T201
        return

    for batch in _batched(pairs, 50):
        for team_id, domain in batch:
            tenant_name = f"team-{team_id}"
            identity_arn = f"arn:aws:ses:{settings.SES_REGION}:{aws_account_id}:identity/{domain}"

            # Create tenant if missing
            try:
                if dry_run:
                    print(f"[DRY-RUN] Would ensure tenant '{tenant_name}' exists")  # noqa: T201
                else:
                    try:
                        tenant_client.create_tenant(
                            TenantName=tenant_name,
                            Tags=[{"Key": "team_id", "Value": str(team_id)}],
                        )
                        print(f"Created SES tenant '{tenant_name}'")  # noqa: T201
                    except ClientError as e:
                        if e.response.get("Error", {}).get("Code") == "AlreadyExistsException":
                            print(f"Tenant '{tenant_name}' already exists")  # noqa: T201
                        else:
                            raise
            except (ClientError, BotoCoreError) as e:
                logger.exception("Error creating SES tenant '%s': %s", tenant_name, e)
                print(f"Error creating tenant '{tenant_name}': {e}")  # noqa: T201
                continue

            # Create association if missing
            try:
                if dry_run:
                    print(f"[DRY-RUN] Would associate identity '{identity_arn}' with tenant '{tenant_name}'")  # noqa: T201
                else:
                    try:
                        tenant_client.create_tenant_resource_association(
                            TenantName=tenant_name,
                            ResourceArn=identity_arn,
                        )
                        print(f"Associated identity '{domain}' with tenant '{tenant_name}'")  # noqa: T201
                    except ClientError as e:
                        if e.response.get("Error", {}).get("Code") == "AlreadyExistsException":
                            print(f"Association already exists for '{domain}' and tenant '{tenant_name}'")  # noqa: T201
                        else:
                            raise
            except (ClientError, BotoCoreError) as e:
                logger.exception(
                    "Error creating SES tenant_resource_association for '%s' on '%s': %s",
                    domain,
                    tenant_name,
                    e,
                )
                print(f"Error creating tenant_resource_association for '{domain}' on '{tenant_name}': {e}")  # noqa: T201
                continue


class Command(BaseCommand):
    help = "Migrate existing SES identities to use SES Tenants and resource associations"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="If set, will not perform changes, only print actions",
        )
        parser.add_argument(
            "--team-ids",
            type=str,
            help="Comma separated list of team ids to migrate",
        )
        parser.add_argument(
            "--domains",
            type=str,
            help="Comma separated list of email domains to migrate (e.g., example.com,foo.bar)",
        )

    def handle(self, *args, **options):
        dry_run: bool = bool(options.get("dry_run"))
        team_ids_opt = options.get("team_ids")
        domains_opt = options.get("domains")

        team_ids = [int(x) for x in team_ids_opt.split(",")] if team_ids_opt else []
        domains = [x.strip() for x in domains_opt.split(",")] if domains_opt else []

        migrate_ses_tenants(team_ids=team_ids, domains=domains, dry_run=dry_run)
