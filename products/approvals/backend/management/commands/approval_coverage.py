"""Report which approval family covers an organization's flags, before and after narrowing.

Scoping policies by flag owner removes coverage from the flags a product owns, so the rollout is
one organization at a time and each step needs the size of the change in front of it first.
"""

from typing import Any, Optional, cast

from django.core.management.base import BaseCommand

from posthog.models import Organization, Team

from products.approvals.backend.actions.registry import ACTION_REGISTRY, register_actions
from products.approvals.backend.models import ApprovalPolicy
from products.approvals.backend.ownership import scope_by_owner_enabled
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.ownership import owner_kind_counts

UNOWNED_LABEL = "(unowned)"
NO_FAMILY = "(none)"


def families_by_owner_kind() -> dict[Optional[str], set[str]]:
    """Which action keys govern each owner kind once an organization is rolled out.

    Read off the registered actions rather than restated here, so this report cannot describe a
    scoping the gate does not apply.
    """
    register_actions()
    families: dict[Optional[str], set[str]] = {}
    for key, action in ACTION_REGISTRY.items():
        if not hasattr(action, "owner_scope"):
            # An action that gates something other than a flag write, such as a holdout change.
            continue
        # Only the flag-write families declare `owner_scope`, and each declares it as `str | None`.
        scope = cast(Optional[str], action.owner_scope)
        families.setdefault(scope, set()).add(key)
    return families


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
        enabled = set(
            ApprovalPolicy.objects.enabled().filter(organization=organization).values_list("action_key", flat=True)
        )
        team_ids = list(Team.objects.filter(organization=organization).values_list("id", flat=True))
        counts = owner_kind_counts(FeatureFlag.objects.filter(team_id__in=team_ids, deleted=False))

        rolled_out = "yes" if scope_by_owner_enabled(organization) else "no"
        self.stdout.write(f"\n{organization.name} ({organization.id})  rolled out: {rolled_out}")
        self.stdout.write(f"  policies: {', '.join(sorted(enabled)) or '(none)'}")
        self.stdout.write(f"  {'owner kind':<22}{'flags':>10}  {'now':<28}{'scoped by owner':<28}")

        moved = lost = 0
        for owner_kind, total in sorted(counts.items(), key=lambda row: -row[1]):
            # Before narrowing every flag is in the unowned family's scope, whoever owns it.
            now = sorted(unowned_family & enabled)
            after = sorted(families.get(owner_kind, set()) & enabled)
            if now and not after:
                lost += total
            elif now and after and now != after:
                moved += total
            self.stdout.write(
                f"  {owner_kind or UNOWNED_LABEL:<22}{total:>10,}  "
                f"{', '.join(now) or NO_FAMILY:<28}{', '.join(after) or NO_FAMILY:<28}"
            )

        self.stdout.write(f"  {moved:,} flags move family, {lost:,} flags lose coverage")
