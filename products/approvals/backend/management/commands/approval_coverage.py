"""Report which approval family covers an organization's flags, before and after narrowing.

Scoping policies by flag owner removes coverage from the flags a product owns, so the rollout is
one organization at a time and each step needs the size of the change in front of it first.
"""

from collections import Counter, defaultdict
from typing import Any, Optional

from django.core.management.base import BaseCommand

from posthog.models import Organization, Team

from products.approvals.backend.coverage import families_by_owner_kind
from products.approvals.backend.models import ApprovalPolicy
from products.approvals.backend.ownership import scope_by_owner_enabled
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.ownership import owner_kind_counts

UNOWNED_LABEL = "(unowned)"
NO_FAMILY = "(none)"


class Command(BaseCommand):
    help = "Show the approval coverage an organization has now and would have scoped by flag owner"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--organization",
            dest="organization_id",
            help="Report one organization by id. Omit to report every organization that has a policy.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        organization_ids = (
            [options["organization_id"]]
            if options.get("organization_id")
            else sorted(
                {str(row) for row in ApprovalPolicy.objects.values_list("organization_id", flat=True).distinct()}
            )
        )
        families = families_by_owner_kind()
        unowned_family = families.get(None, set())

        for organization_id in organization_ids:
            organization = Organization.objects.filter(id=organization_id).first()
            if organization is None:
                self.stderr.write(f"No organization {organization_id}")
                continue
            self._report(organization, families, unowned_family)

    def _report(
        self,
        organization: Organization,
        families: dict[Optional[str], set[str]],
        unowned_family: set[str],
    ) -> None:
        enabled = ApprovalPolicy.objects.enabled().filter(organization=organization)
        organization_keys = set(enabled.filter(team__isnull=True).values_list("action_key", flat=True))
        team_keys: dict[int, set[str]] = defaultdict(set)
        for team_id, action_key in enabled.filter(team__isnull=False).values_list("team_id", "action_key"):
            team_keys[team_id].add(action_key)

        rolled_out = "yes" if scope_by_owner_enabled(organization) else "no"
        self.stdout.write(f"\n{organization.name} ({organization.id})  rolled out: {rolled_out}")
        self.stdout.write(f"  organization policies: {', '.join(sorted(organization_keys)) or '(none)'}")
        self.stdout.write(f"  {'owner kind':<22}{'flags':>10}  {'now':<28}{'scoped by owner':<28}")

        # A team policy governs only its own team's flags, so each team is resolved on its own.
        rows: Counter[tuple[Optional[str], tuple[str, ...], tuple[str, ...]]] = Counter()
        moved = lost = 0
        for team_id in Team.objects.filter(organization=organization).values_list("id", flat=True):
            applicable = organization_keys | team_keys.get(team_id, set())
            counts = owner_kind_counts(FeatureFlag.objects.filter(team_id=team_id, deleted=False))
            for owner_kind, total in counts.items():
                # Before narrowing every flag is in the unowned family's scope, whoever owns it.
                now = tuple(sorted(unowned_family & applicable))
                after = tuple(sorted(families.get(owner_kind, set()) & applicable))
                rows[(owner_kind, now, after)] += total
                if now and not after:
                    lost += total
                elif now and after and now != after:
                    moved += total

        for (owner_kind, now, after), total in sorted(rows.items(), key=lambda row: -row[1]):
            self.stdout.write(
                f"  {owner_kind or UNOWNED_LABEL:<22}{total:>10,}  "
                f"{', '.join(now) or NO_FAMILY:<28}{', '.join(after) or NO_FAMILY:<28}"
            )

        self.stdout.write(f"  {moved:,} flags move family, {lost:,} flags lose coverage")
