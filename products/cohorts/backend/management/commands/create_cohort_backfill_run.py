from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import IntegrityError
from django.utils import timezone as django_timezone
from django.utils.dateparse import parse_datetime

from posthog.models.team.team import Team

from products.cohorts.backend.backfill.pinning import (
    PersonPinningCapExceeded,
    pin_conditions_for_cohorts,
    pin_person_conditions_for_cohorts,
)
from products.cohorts.backend.backfill.runs import (
    _validate_boundary_at,
    check_person_run_preconditions,
    check_run_preconditions,
    create_person_team_backfill_run,
    create_team_backfill_run,
    has_behavioral_filters,
    person_backfill_ineligibility_reason,
)
from products.cohorts.backend.backfill.sizing import estimate_person_seed_topic_bytes
from products.cohorts.backend.models.backfill import CohortBackfillKind, CohortBackfillRunCohort, CohortBackfillTrigger
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.leaf_shape import walk_filter_leaves
from products.cohorts.backend.realtime_teams import is_realtime_cohort_team


def _parse_boundary_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        boundary_at = parse_datetime(value)
    except ValueError as error:
        raise CommandError("--boundary-at must be a valid ISO 8601 timestamp with a UTC offset") from error
    if boundary_at is None:
        raise CommandError("--boundary-at must be a valid ISO 8601 timestamp with a UTC offset")
    if django_timezone.is_naive(boundary_at):
        raise CommandError("--boundary-at must include a UTC offset")
    return boundary_at


class Command(BaseCommand):
    help = "Create a coordinated cohort backfill run"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--trigger",
            choices=[CohortBackfillTrigger.TEAM_ENABLEMENT, CohortBackfillTrigger.DISASTER_RECOVERY],
            required=True,
        )
        parser.add_argument(
            "--kind",
            choices=[value for value, _label in CohortBackfillKind.choices],
            default=CohortBackfillKind.BEHAVIORAL,
        )
        parser.add_argument("--cohort-ids", type=int, nargs="+")
        parser.add_argument("--boundary-at", help="ISO 8601 disaster recovery boundary with a UTC offset")
        parser.add_argument("--person-horizon-days", type=int)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        trigger: str = options["trigger"]
        kind: str = options["kind"]
        person_horizon_days: int | None = options.get("person_horizon_days")
        boundary_at = _parse_boundary_at(options.get("boundary_at"))
        if boundary_at is not None and trigger != CohortBackfillTrigger.DISASTER_RECOVERY:
            raise CommandError("--boundary-at is only valid with --trigger disaster_recovery")
        if kind == CohortBackfillKind.PERSON_PROPERTY and person_horizon_days is None:
            raise CommandError("--person-horizon-days is required with --kind person_property")
        if kind == CohortBackfillKind.BEHAVIORAL and person_horizon_days is not None:
            raise CommandError("--person-horizon-days is only valid with --kind person_property")

        if not is_realtime_cohort_team(team_id):
            raise CommandError(f"Team {team_id} is not in the realtime cohort allowlist")

        if kind == CohortBackfillKind.PERSON_PROPERTY:
            assert person_horizon_days is not None
            self._handle_person_run(
                team_id=team_id,
                trigger=trigger,
                person_horizon_days=person_horizon_days,
                cohort_ids=options.get("cohort_ids"),
                boundary_at=boundary_at,
                dry_run=options["dry_run"],
            )
            return

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
            cohorts = [cohort for cohort in queryset.order_by("id") if has_behavioral_filters(cohort)]
            if cohort_ids is not None and {cohort.id for cohort in cohorts} != set(cohort_ids):
                raise CommandError("One or more --cohort-ids are not eligible realtime behavioral cohorts")
            pinned, event_names = pin_conditions_for_cohorts(cohorts)
            self.stdout.write(
                f"Dry run: {len(cohorts)} cohorts, {len(pinned['conditions'])} conditions, "
                f"{len(event_names)} event names"
            )
            return

        try:
            run = create_team_backfill_run(team_id, trigger, cohort_ids, boundary_at=boundary_at)
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

    def _handle_person_run(
        self,
        *,
        team_id: int,
        trigger: str,
        person_horizon_days: int,
        cohort_ids: list[int] | None,
        boundary_at: datetime | None,
        dry_run: bool,
    ) -> None:
        _, missing = check_person_run_preconditions()
        if missing:
            raise CommandError(f"Missing operator attestations: {', '.join(missing)}")
        if person_horizon_days < 1:
            raise CommandError("--person-horizon-days must be at least 1")

        if dry_run:
            self._person_dry_run(
                team_id=team_id,
                trigger=trigger,
                person_horizon_days=person_horizon_days,
                cohort_ids=cohort_ids,
                boundary_at=boundary_at,
            )
            return

        try:
            run = create_person_team_backfill_run(
                team_id,
                trigger,
                person_horizon_days,
                cohort_ids,
                boundary_at=boundary_at,
            )
        except (Team.DoesNotExist, ValueError) as error:
            raise CommandError(str(error)) from error
        except IntegrityError as error:
            raise CommandError(f"Team {team_id} already has an active person-property team backfill run") from error

        self.stdout.write(
            self.style.SUCCESS(
                f"Created person-property run {run.id}: "
                f"{CohortBackfillRunCohort.objects.for_team(team_id).filter(run=run).count()} cohorts, "
                f"{len(run.pinned['conditions'])} conditions, "
                f"{run.preconditions['person_seed_estimated_persons']} estimated persons, "
                f"{run.preconditions['person_seed_estimated_topic_bytes']} estimated topic bytes"
            )
        )

    def _person_dry_run(
        self,
        *,
        team_id: int,
        trigger: str,
        person_horizon_days: int,
        cohort_ids: list[int] | None,
        boundary_at: datetime | None,
    ) -> None:
        requested_ids = set(cohort_ids) if cohort_ids is not None else None
        # Deliberately wider than `_person_cohorts_for_team`, which narrows the SQL-expressible half
        # of eligibility away before it locks: the dry run's whole job is naming *why* each cohort was
        # refused, and it takes no locks. Both sides decide with `person_backfill_ineligibility_reason`.
        queryset = Cohort.objects.filter(team_id=team_id)
        if requested_ids is not None:
            queryset = queryset.filter(id__in=requested_ids)
        candidates = [(cohort, person_backfill_ineligibility_reason(cohort)) for cohort in queryset.order_by("id")]

        refusals = [(cohort.id, reason) for cohort, reason in candidates if reason is not None]
        if requested_ids is not None:
            candidate_ids = {cohort.id for cohort, _ in candidates}
            refusals.extend((cohort_id, "not found") for cohort_id in sorted(requested_ids - candidate_ids))

        if refusals:
            self.stdout.write(
                "Refused cohorts: " + ", ".join(f"{cohort_id} ({reason})" for cohort_id, reason in refusals)
            )
        if requested_ids is not None and refusals:
            raise CommandError("One or more --cohort-ids are not eligible realtime person-property cohorts")

        cohorts = [cohort for cohort, reason in candidates if reason is None]
        if not cohorts:
            raise CommandError(f"Team {team_id} has no eligible realtime person-property cohorts")
        try:
            pinned = pin_person_conditions_for_cohorts(
                cohorts,
                max_conditions=settings.BEHAVIORAL_BACKFILL_PERSON_MAX_PINNED_CONDITIONS,
            )
        except PersonPinningCapExceeded as error:
            raise CommandError(str(error)) from error

        dropped = sum(
            1
            for cohort in cohorts
            for leaf in walk_filter_leaves((cohort.filters or {}).get("properties"))
            if leaf.get("type") == "person" and leaf.get("conditionHash") is None
        )
        try:
            normalized_boundary = _validate_boundary_at(trigger, boundary_at)
            person_scan_since = (normalized_boundary or django_timezone.now()) - timedelta(days=person_horizon_days)
        except (OverflowError, ValueError) as error:
            raise CommandError(str(error)) from error
        estimate = estimate_person_seed_topic_bytes(
            team_id,
            person_scan_since,
            len(pinned["conditions"]),
        )
        verdict = "yes" if estimate.over_budget else "no"
        self.stdout.write(
            f"Dry run: {len(cohorts)} cohorts, {len(pinned['conditions'])} conditions, "
            f"{dropped} hash-less person leaves dropped, {estimate.estimated_persons} estimated persons, "
            f"{estimate.estimated_topic_bytes} estimated topic bytes, budget {estimate.budget_bytes}, "
            f"would refuse: {verdict}"
        )
