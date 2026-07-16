from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import IntegrityError

from posthog.models.team.team import Team

from products.cohorts.backend.backfill.pinning import pin_conditions_for_cohorts
from products.cohorts.backend.backfill.runs import check_run_preconditions, create_team_backfill_run
from products.cohorts.backend.models.backfill import CohortBackfillRunCohort, CohortBackfillTrigger
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.leaf_shape import walk_filter_leaves
from products.cohorts.backend.realtime_teams import is_realtime_cohort_team


def _has_behavioral_filters(cohort: Cohort) -> bool:
    return any(
        leaf.get("type") == "behavioral" for leaf in walk_filter_leaves((cohort.filters or {}).get("properties"))
    )


class Command(BaseCommand):
    help = "Create a coordinated behavioral cohort backfill run"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--trigger",
            choices=[CohortBackfillTrigger.TEAM_ENABLEMENT, CohortBackfillTrigger.DISASTER_RECOVERY],
            required=True,
        )
        parser.add_argument("--cohort-ids", type=int, nargs="+")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        if not is_realtime_cohort_team(team_id):
            raise CommandError(f"Team {team_id} is not in the realtime cohort allowlist")

        _, missing = check_run_preconditions()
        if missing:
            raise CommandError(f"Missing operator attestations: {', '.join(missing)}")

        cohort_ids = options.get("cohort_ids")
        if options["dry_run"]:
            queryset = Cohort.objects.filter(
                team_id=team_id,
                cohort_type=CohortType.REALTIME,
                is_static=False,
                deleted=False,
            )
            if cohort_ids is not None:
                queryset = queryset.filter(id__in=cohort_ids)
            cohorts = [cohort for cohort in queryset.order_by("id") if _has_behavioral_filters(cohort)]
            if cohort_ids is not None and {cohort.id for cohort in cohorts} != set(cohort_ids):
                raise CommandError("One or more --cohort-ids are not eligible realtime behavioral cohorts")
            pinned, event_names = pin_conditions_for_cohorts(cohorts)
            self.stdout.write(
                f"Dry run: {len(cohorts)} cohorts, {len(pinned['conditions'])} conditions, "
                f"{len(event_names)} event names"
            )
            return

        try:
            run = create_team_backfill_run(team_id, options["trigger"], cohort_ids)
        except (Team.DoesNotExist, ValueError) as error:
            raise CommandError(str(error)) from error
        except IntegrityError as error:
            raise CommandError(f"Team {team_id} already has an active team backfill run") from error
        self.stdout.write(
            self.style.SUCCESS(
                f"Created run {run.id}: "
                f"{CohortBackfillRunCohort.objects.for_team(team_id).filter(run=run).count()} cohorts, "
                f"{len(run.pinned['conditions'])} conditions, {len(run.pinned['event_names'])} event names"
            )
        )
