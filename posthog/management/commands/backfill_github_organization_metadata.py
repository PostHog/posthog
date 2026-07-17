import logging

from django.core.management.base import BaseCommand
from django.core.paginator import Paginator

from posthog.models.github_metadata import normalize_github_account_type, project_github_metadata_onto_organization
from posthog.models.integration import Integration
from posthog.models.team.team import Team

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Project connect-time GitHub facts (account type, repository selection/count) onto each "
        "integration's organization group. Reads only stored config; never calls the GitHub API."
    )

    def add_arguments(self, parser):
        parser.add_argument("--page-size", type=int, default=500, help="Integrations processed per page.")
        parser.add_argument("--dry-run", action="store_true", help="Log intended writes without emitting them.")

    def handle(self, *args, **options):
        page_size = options["page_size"]
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no group properties will be written"))

        queryset = Integration.objects.filter(kind="github").order_by("id").values("id", "team_id", "config")
        total = queryset.count()
        self.stdout.write(f"Found {total} GitHub integrations")

        team_org: dict[int, str | None] = {}
        written = 0
        skipped = 0

        paginator = Paginator(queryset, page_size)
        for page_num in paginator.page_range:
            for row in paginator.page(page_num).object_list:
                account_type = normalize_github_account_type(((row["config"] or {}).get("account") or {}).get("type"))
                repository_selection = (row["config"] or {}).get("repository_selection")
                repository_count = (row["config"] or {}).get("repository_count")

                if account_type is None and repository_selection is None and repository_count is None:
                    skipped += 1
                    continue

                team_id = row["team_id"]
                if team_id not in team_org:
                    org_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
                    team_org[team_id] = str(org_id) if org_id is not None else None
                organization_id = team_org[team_id]
                if organization_id is None:
                    skipped += 1
                    continue

                if dry_run:
                    self.stdout.write(
                        f"  would project org={organization_id} account_type={account_type} "
                        f"selection={repository_selection} count={repository_count}"
                    )
                    written += 1
                    continue

                if project_github_metadata_onto_organization(
                    organization_id=organization_id,
                    account_type=account_type,
                    repository_selection=repository_selection,
                    repository_count=repository_count,
                ):
                    written += 1
                else:
                    skipped += 1

        verb = "would project" if dry_run else "projected"
        self.stdout.write(self.style.SUCCESS(f"Done. {verb} {written}, skipped {skipped} of {total}"))
