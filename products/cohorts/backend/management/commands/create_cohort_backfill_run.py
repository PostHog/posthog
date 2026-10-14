from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import IntegrityError
from django.utils import timezone as django_timezone
from django.utils.dateparse import parse_datetime

from posthog.errors import InternalCHQueryError
from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.models.team.team import Team

from products.cohorts.backend.backfill.pinning import (
    PersonPinningCapExceeded,
    pin_conditions_for_cohorts,
    pin_person_conditions_for_cohorts,
)
from products.cohorts.backend.backfill.runs import (
    _validate_boundary_at,
    behavioral_backfill_ineligibility_reason,
    check_person_run_preconditions,
    check_run_preconditions,
    create_person_team_backfill_run,
    create_team_backfill_run,
    judge_team_cohorts,
    person_backfill_ineligibility_reason,
)
from products.cohorts.backend.backfill.sizing import (
    BehavioralScanEstimate,
    PersonSeedEstimateScanCapExceeded,
    estimate_behavioral_scan_events,
    estimate_person_seed_topic_bytes,
)
from products.cohorts.backend.models.backfill import CohortBackfillKind, CohortBackfillRunCohort, CohortBackfillTrigger
from products.cohorts.backend.models.cohort import Cohort
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
        parser.add_argument(
            "--max-scan-events-per-day",
            type=int,
            help=(
                "Behavioral runs only: refuse the run when its pinned event names had more events than this on "
                "any of the last 7 complete UTC days. Overrides BEHAVIORAL_BACKFILL_MAX_SCAN_EVENTS_PER_DAY; "
                "0 disables it."
            ),
        )
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
        max_scan_events_per_day: int | None = options.get("max_scan_events_per_day")
        if kind == CohortBackfillKind.PERSON_PROPERTY and max_scan_events_per_day is not None:
            raise CommandError("--max-scan-events-per-day is only valid with --kind behavioral")
        if max_scan_events_per_day is None:
            max_scan_events_per_day = settings.BEHAVIORAL_BACKFILL_MAX_SCAN_EVENTS_PER_DAY
        if max_scan_events_per_day < 0:
            raise CommandError("--max-scan-events-per-day must be 0 or more")

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
            cohorts = self._dry_run_cohorts(team_id, cohort_ids, behavioral_backfill_ineligibility_reason, "behavioral")
            pinned, event_names = pin_conditions_for_cohorts(cohorts)
            self.stdout.write(
                f"Dry run: {len(cohorts)} cohorts, {len(pinned['conditions'])} conditions, "
                f"{len(event_names)} event names"
            )
            if max_scan_events_per_day:
                self._write_scan_estimate(
                    self._scan_estimate(team_id, event_names, max_scan_events_per_day), len(event_names)
                )
            else:
                self.stdout.write("Scan estimate: skipped, because the limit is 0")
            return

        scan_estimate: BehavioralScanEstimate | None = None
        if max_scan_events_per_day:
            # Estimated before the creator locks the cohorts, so an edit in between can shift the names.
            # The limit is a preflight, not a guarantee: the save path creates runs without it.
            eligible = [
                cohort
                for cohort, reason in judge_team_cohorts(team_id, cohort_ids, behavioral_backfill_ineligibility_reason)
                if reason is None
            ]
            _, event_names = pin_conditions_for_cohorts(eligible)
            scan_estimate = self._scan_estimate(team_id, event_names, max_scan_events_per_day)
            self._write_scan_estimate(scan_estimate, len(event_names))
            if scan_estimate.over_limit:
                raise CommandError(
                    f"The run would scan {scan_estimate.peak_day_events} events on its busiest day "
                    f"({scan_estimate.peak_day}), above the limit of {scan_estimate.max_events_per_day}. "
                    "Narrow it with --cohort-ids, or pass --max-scan-events-per-day to accept the volume."
                )

        try:
            run = create_team_backfill_run(
                team_id, trigger, cohort_ids, boundary_at=boundary_at, scan_estimate=scan_estimate
            )
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
        except (Team.DoesNotExist, ValueError, PersonSeedEstimateScanCapExceeded) as error:
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
        cohorts = self._dry_run_cohorts(team_id, cohort_ids, person_backfill_ineligibility_reason, "person-property")
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
        try:
            estimate = estimate_person_seed_topic_bytes(
                team_id,
                person_scan_since,
                len(pinned["conditions"]),
            )
        except PersonSeedEstimateScanCapExceeded as error:
            raise CommandError(str(error)) from error
        verdict = "yes" if estimate.over_budget else "no"
        self.stdout.write(
            f"Dry run: {len(cohorts)} cohorts, {len(pinned['conditions'])} conditions, "
            f"{dropped} hash-less person leaves dropped, {estimate.estimated_persons} estimated persons, "
            f"{estimate.estimated_topic_bytes} estimated topic bytes, budget {estimate.budget_bytes}, "
            f"would refuse: {verdict}"
        )

    def _scan_estimate(self, team_id: int, event_names: list[str], max_events_per_day: int) -> BehavioralScanEstimate:
        try:
            return estimate_behavioral_scan_events(team_id, event_names, max_events_per_day=max_events_per_day)
        except (
            ClickHouseQueryTimeOut,
            ClickHouseEstimatedQueryExecutionTimeTooLong,
            ClickHouseQueryMemoryLimitExceeded,
            ClickHouseAtCapacity,
            InternalCHQueryError,
        ) as error:
            raise CommandError(
                f"The scan estimate failed: {error}. Pass --max-scan-events-per-day 0 to create the run without it."
            ) from error

    def _write_scan_estimate(self, estimate: BehavioralScanEstimate, event_name_count: int) -> None:
        largest = ", ".join(f"{name} {count}" for name, count in estimate.largest_events(5)) or "none"
        verdict = "yes" if estimate.over_limit else "no"
        self.stdout.write(
            f"Scan estimate: {estimate.peak_day_events} events on the busiest of the last {estimate.days_sampled} "
            f"complete UTC days ({estimate.peak_day or 'no events'}) across {event_name_count} event names, "
            f"limit {estimate.max_events_per_day}, would refuse: {verdict}. Largest on that day: {largest}"
        )

    def _dry_run_cohorts(
        self,
        team_id: int,
        cohort_ids: list[int] | None,
        ineligibility_reason: Callable[[Cohort], str | None],
        kind_label: str,
    ) -> list[Cohort]:
        candidates = judge_team_cohorts(team_id, cohort_ids, ineligibility_reason)
        refusals = [(cohort.id, reason) for cohort, reason in candidates if reason is not None]
        if cohort_ids is not None:
            candidate_ids = {cohort.id for cohort, _ in candidates}
            refusals.extend((cohort_id, "not found") for cohort_id in sorted(set(cohort_ids) - candidate_ids))

        if refusals:
            self.stdout.write(
                "Refused cohorts: " + ", ".join(f"{cohort_id} ({reason})" for cohort_id, reason in refusals)
            )
        if cohort_ids is not None and refusals:
            raise CommandError(f"One or more --cohort-ids are not eligible realtime {kind_label} cohorts")

        cohorts = [cohort for cohort, reason in candidates if reason is None]
        if not cohorts:
            raise CommandError(f"Team {team_id} has no eligible realtime {kind_label} cohorts")
        return cohorts
