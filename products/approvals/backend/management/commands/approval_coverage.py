"""Report which approval family covers an organization's flags, before and after narrowing.

Scoping policies by flag owner removes coverage from the flags a product owns, so the rollout is
one organization at a time and each step needs the size of the change in front of it first.
"""

from collections import Counter
from typing import Any, Optional

from django.core.management.base import BaseCommand

from posthog.models import Organization, Team

from products.approvals.backend.coverage import cover_dropped, governing_gates
from products.approvals.backend.models import ApprovalPolicy
from products.approvals.backend.ownership import scope_by_owner_state
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.ownership import owner_kind_counts

UNOWNED_LABEL = "(unowned)"
NO_FAMILY = "(none)"
# The sync skips an organization whose state is unknown, so the report must not show it as "no".
ROLLOUT_LABELS = {True: "yes", False: "no", None: "unknown, so the policy sync skips it"}


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

        for organization_id in organization_ids:
            organization = Organization.objects.filter(id=organization_id).first()
            if organization is None:
                self.stderr.write(f"No organization {organization_id}")
                continue
            self._report(organization)

    def _report(self, organization: Organization) -> None:
        organization_keys = sorted(
            set(
                ApprovalPolicy.objects.enabled()
                .filter(organization=organization, team__isnull=True)
                .values_list("action_key", flat=True)
            )
        )

        rolled_out = ROLLOUT_LABELS[scope_by_owner_state(organization)]
        self.stdout.write(f"\n{organization.name} ({organization.id})  rolled out: {rolled_out}")
        self.stdout.write(f"  organization policies: {', '.join(organization_keys) or '(none)'}")
        self.stdout.write(
            f"  {'owner kind':<22}{'flags':>10}  {'not scoped':<28}{'scoped by owner':<28}{'loses cover':<12}"
        )

        # Compared write by write with the adoption guard's rule, so a family whose policies gate
        # fewer writes, other changes or more bypass counts as a loss, not a move.
        rows: Counter[tuple[Optional[str], tuple[str, ...], tuple[str, ...], bool]] = Counter()
        moved = lost = 0
        for team in Team.objects.filter(organization=organization):
            # Before scoping, the unowned family's policies govern every flag, whoever owns it.
            governed_now = governing_gates(None, team, organization)
            counts = owner_kind_counts(FeatureFlag.objects.filter(team_id=team.id, deleted=False))
            for owner_kind, total in counts.items():
                governed_after = governing_gates(owner_kind, team, organization)
                drops = cover_dropped(governed_now, governed_after)
                rows[(owner_kind, tuple(sorted(governed_now)), tuple(sorted(governed_after)), drops)] += total
                if drops:
                    lost += total
                elif governed_now and owner_kind is not None:
                    moved += total

        for (owner_kind, now, after, drops), total in sorted(rows.items(), key=lambda row: -row[1]):
            self.stdout.write(
                f"  {owner_kind or UNOWNED_LABEL:<22}{total:>10,}  "
                f"{', '.join(now) or NO_FAMILY:<28}{', '.join(after) or NO_FAMILY:<28}{'yes' if drops else 'no':<12}"
            )

        self.stdout.write(f"  {moved:,} flags move family, {lost:,} flags lose coverage")
