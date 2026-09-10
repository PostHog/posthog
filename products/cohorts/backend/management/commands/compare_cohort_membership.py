"""Classified parity report: new Rust cohort pipeline vs an oracle.

Three oracle modes select what the folded shadow topic (the new pipeline's converged membership) is
compared against:

- ``--oracle old-pipeline`` (default): the argMax of ClickHouse ``cohort_membership`` — the legacy
  Temporal recompute. The diff is bounded to the observed universe O = persons the new pipeline
  decided on since the store wipe; never-computed persons (old - O) are excluded from the gate and
  feed a separate missed-emission probe. Divergences are classified (R-FRESH / R-STALE /
  suspect-missing / dormant) so expected skew is separated from real bugs.

- ``--oracle recompute``: membership recomputed from ``events`` with evaluator semantics (window,
  count>=1 floor, operator, tree composition), then diffed with backfill-aware segmentation — the
  productized form of the hand-rolled backfill canary verification. Over-count (fold - oracle) is the
  hard gate; under-count (oracle - fold) is segmented by day-domain so the boundary-day decay gap is
  separated from real seed/unseeded misses.

- ``--oracle population``: the population the legacy batch calculation wrote to ClickHouse
  ``cohortpeople`` at the cohort's pinned ``version`` — the set the cohort page shows. The fold is
  bounded to each cohort's ``last_calculation`` and the two sets are diffed directly. No filter is
  read, so no cohort shape is unsupported; equally, nothing is adjudicated. Report-only, always
  exits 0.

Run from a toolbox/web pod (needs KAFKA_INGESTION_HOSTS + the offline ClickHouse host):

    manage.py compare_cohort_membership --team-id 2 --since "2026-07-07T19:11:00Z"
    manage.py compare_cohort_membership --team-id 2 --cohort-id 433564 --since "2026-07-24T02:00:00Z" --oracle recompute
    manage.py compare_cohort_membership --team-id 2 --since "2026-07-07T19:11:00Z" --oracle population
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import chain
from typing import Any, Optional
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team.team import Team

from products.cohorts.backend.backfill.pinning import pin_conditions_for_cohorts
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.parity.classifier import ClassifierConfig, CohortComparison, classify_cohort, summarize
from products.cohorts.backend.parity.eligibility import EMITTING_CLASSES, ScreenedCohort, screen_team
from products.cohorts.backend.parity.fold import fold_membership_changes, members, reconcile_completeness_by_cohort
from products.cohorts.backend.parity.kafka_io import (
    DEFAULT_MARKER_TOPIC,
    DEFAULT_SHADOW_TOPIC,
    DrainStats,
    consumer_config,
    drain_topic,
)
from products.cohorts.backend.parity.oracle import (
    OracleSetTooLarge,
    load_day_counts,
    load_leaf_match_counts,
    load_leaf_members,
    load_run_context,
    run_with_boundary_exists,
)
from products.cohorts.backend.parity.population import (
    PopulationComparison,
    compare_populations,
    skip_population,
    summarize_population,
)
from products.cohorts.backend.parity.recompute import (
    ExtendedLeafCounts,
    RecomputeComparison,
    RecomputeUnsupported,
    RunContext,
    classify_recompute,
    compute_oracle_members,
    screen_for_recompute,
    segmentation_blocker,
    skip_comparison,
    summarize_recompute,
)
from products.cohorts.backend.parity.report import (
    format_notes,
    format_population_summary,
    format_population_table,
    format_recompute_notes,
    format_recompute_summary,
    format_recompute_table,
    format_reconcile_notes,
    format_summary,
    format_table,
    to_json,
    to_population_json,
    to_recompute_json,
)
from products.cohorts.backend.parity.snapshots import (
    load_cohort_population,
    load_old_membership,
    load_realtime_cohorts,
    make_activity_probe,
)
from products.cohorts.backend.parity.tzdates import resolve_zoneinfo, window_start_utc

SHADOW_TOPIC_RETENTION_DAYS = 7
# A pinned --at well behind the drain is sound (the fold converges to the same instant) but describes
# a past state: reconcile markers and decisions made since are excluded, so say so.
RECOMPUTE_STALE_AT_MINUTES = 15

DEFAULT_THRESHOLD_PCT = 0.5
DEFAULT_WARMUP_SAMPLE = 5000
DEFAULT_GRACE_MINUTES = 10
# A cohort window wider than this drives an unbounded `events` scan for no diagnostic gain; the Rust
# side treats such a window as "never evicts" rather than sliding, so SKIP instead of scanning.
DEFAULT_MAX_WINDOW_DAYS = 400
# The oracle reads (leaf recompute, cohortpeople population) materialize whole member sets in
# Python; past this they OOM a toolbox pod.
DEFAULT_MAX_ORACLE_MEMBERS = 1_000_000
# Grace is also the sweep-lag horizon, so a whole day of it would swallow the boundary day.
MAX_GRACE_MINUTES = 24 * 60
# Persons per diff side that the per-person reads will chunk through (1000 ids per query).
MAX_DIFF_TARGETS = 50_000
# The eviction split asks whether a false member is still a member one day-slide back.
EVICTION_LOOKBACK_DAYS = 1

# Deliberate coverage limits, restated with every report so a clean run is not over-read.
COVERAGE_CAVEATS = (
    "the diff is bounded to persons the new pipeline decided on (O); old-only persons outside O are excluded and only probed for missed emissions",
    "suspect_missing gates FAIL only where the store provably covers the window (window <= pipeline age, or property-only cohorts); on longer windows unobserved actives are unresolvable until warmup (no snapshot resolves pre-since qualifiers) and report as WARMUP",
    "minute/hour-window cohorts get suspect≈0 by construction — the probe cutoff collapses to now",
    "cohorts with no recompute clock (never recomputed, or the stamp cleared by an edit) count all only_new as fresh (residual_new is 0 there)",
    "a partial drain (poll timeout or --max-messages) understates the new side and biases toward FAIL",
)

RECOMPUTE_CAVEATS = (
    "the oracle reproduces only performed_event / performed_event_multiple leaves with a string event key, no event_filters (property matching is HogVM bytecode, not SQL), and whole-day sliding windows within --max-window-days; everything else SKIPs",
    "over-count (false_members) is the hard gate; the sweep-lag share — still a member one day-slide back, or entered within --grace-minutes — is reported but not gated",
    "under-count segmentation needs a single supported leaf, a monotone op (gte/gt), a backfill run, and a grace window opening after that run's boundary; without them the cohort reports SKIP (parity not established), never PASS",
    "past the per-person read cap the two sides fail differently: over-count keeps scoring every false member hard (FAIL), since over-inclusion is the hard invariant, while under-count drops to unsegmented (SKIP); a cap-driven FAIL is called out in the cohort notes and is not on its own evidence of over-inclusion",
    "missing_boundary_day is the expected decaying gap; missing_seed_domain, missing_unseeded_day and missing_post_boundary gate FAIL — raise --grace-minutes to absorb known live-path lag",
    "day boundaries use the current team tz, the only tz the processor uses; a run pinned to a different tz SKIPs rather than mis-attributing seed days",
    "the oracle counts only events ingested by --at (the seeder's inserted_at cutoff), so a longer ingestion lag reads as neither over- nor under-count",
    "override/merge drift (fold ids resolved at processing time vs the oracle's current overrides) can pair a false_member with a missing person; a bounded per-class person-id sample ships in the JSON for triage",
)

POPULATION_CAVEATS = (
    "this diffs two independent pipelines and deliberately does not say which side is right",
    "without a complete 64/64 reconcile run in the fold the pipeline emits membership flips only, so only_legacy is an upper bound on real misses rather than a miss count",
    "the fold is bounded to each cohort's last_calculation, but the legacy calculation itself ran over some minutes and read ClickHouse with ingestion lag behind it, so minutes of skew on both sides is expected",
    "a partial drain (poll timeout or --max-messages) understates the fold side",
)


def _collect_warnings(
    drain_stats: DrainStats,
    unknown_cohorts: set[int],
    since: datetime,
    now: datetime,
) -> tuple[list[str], list[str]]:
    """Pure: derive operator (warnings, info lines) from drain results and the clock."""
    warnings: list[str] = []
    infos: list[str] = []
    if drain_stats.earliest_retained is not None:
        message = f"earliest retained shadow message: {drain_stats.earliest_retained.isoformat()}"
        if drain_stats.maybe_clipped_partitions:
            warnings.append(
                message + f" — retention already clipped partitions {sorted(drain_stats.maybe_clipped_partitions)} "
                "past --since; the fold may be incomplete"
            )
        else:
            infos.append(message)
    if not drain_stats.reached_end:
        warnings.append(
            "drain stopped before the high-watermark snapshot (poll timeout or --max-messages); fold is partial"
        )
    retention_deadline = since + timedelta(days=SHADOW_TOPIC_RETENTION_DAYS)
    if now > retention_deadline - timedelta(days=1):
        warnings.append(
            f"fold-from-topic completeness expires ~{retention_deadline.date()} ({SHADOW_TOPIC_RETENTION_DAYS}d "
            "topic retention) — ship the shadow materializer before then"
        )
    if unknown_cohorts:
        warnings.append(
            f"shadow topic contains {len(unknown_cohorts)} cohort id(s) absent from the realtime universe "
            f"(deleted/retyped since?): {sorted(unknown_cohorts)[:20]}"
        )
    return warnings, infos


@dataclass(frozen=True)
class RecomputeCohortState:
    cohort_id: int
    ctx: Optional[RunContext]
    has_complete_reconcile: bool


def _collect_recompute_warnings(
    *,
    at: datetime,
    now: datetime,
    team_timezone: str,
    states: list[RecomputeCohortState],
) -> list[str]:
    """Pure: recompute-specific operator warnings — stale clock and per-cohort run-context caveats."""
    warnings: list[str] = []
    stale = now - at
    if stale > timedelta(minutes=RECOMPUTE_STALE_AT_MINUTES):
        warnings.append(
            f"--at is {int(stale.total_seconds() // 60)}m before now; the fold is bounded to it, so this "
            "report describes that instant rather than the current pipeline state"
        )
    for state in states:
        if state.ctx is None:
            warnings.append(
                f"cohort {state.cohort_id}: no backfill run with a boundary; the missing set is left unsegmented"
            )
            continue
        if state.ctx.run_timezone != team_timezone:
            warnings.append(
                f"cohort {state.cohort_id}: run tz {state.ctx.run_timezone} != team tz {team_timezone}; seed-chunk "
                "days cannot be attributed to the team-tz days the processor bins by, so the cohort is SKIPPED"
            )
        if state.ctx.shape_hash_drift:
            warnings.append(
                f"cohort {state.cohort_id}: behavioral filters changed since the run was pinned (shape-hash "
                "drift); the seed domain may be stale"
            )
        if state.ctx.non_confirmed_chunks > 0:
            warnings.append(
                f"cohort {state.cohort_id}: {state.ctx.non_confirmed_chunks} seed chunk(s) not confirmed; the "
                "seed domain is partial"
            )
        if not state.has_complete_reconcile:
            warnings.append(
                f"cohort {state.cohort_id}: no complete 64/64 reconcile run folded; over-counts may be spurious"
            )
    return warnings


@dataclass(frozen=True)
class PopulationCohortState:
    cohort_id: int
    last_calculation: datetime
    is_calculating: bool
    has_complete_reconcile: bool


def _collect_population_warnings(*, now: datetime, states: list[PopulationCohortState]) -> list[str]:
    """Pure: the three ways a compared population row can be misread."""
    warnings: list[str] = []
    retention_floor = now - timedelta(days=SHADOW_TOPIC_RETENTION_DAYS)
    for state in states:
        if not state.has_complete_reconcile:
            warnings.append(
                f"cohort {state.cohort_id}: no complete 64/64 reconcile run folded; the fold carries only persons "
                "the pipeline decided on since --since, so only_legacy is an upper bound on real misses"
            )
        if state.last_calculation < retention_floor:
            warnings.append(
                f"cohort {state.cohort_id}: last_calculation {state.last_calculation.isoformat()} is behind the "
                f"{SHADOW_TOPIC_RETENTION_DAYS}d shadow-topic retention floor; the fold cannot reach back that far"
            )
        if state.is_calculating:
            warnings.append(f"cohort {state.cohort_id}: is_calculating is set; the legacy population is mid-rewrite")
    return warnings


def _parse_iso_utc(raw: str, flag: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as err:
        raise CommandError(f"{flag} is not ISO8601: {raw!r}") from err
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_since(raw: str) -> datetime:
    return _parse_iso_utc(raw, "--since")


def _within_target_cap(targets: list[str], side: str, notes: list[str]) -> bool:
    """Whether a diff side is small enough to drive per-person reads (1000 ids per query).

    A blown cap is recorded in the report rather than silently truncated: past it the diagnostic
    would run tens of thousands of sequential `events` scans on the offline pool.
    """
    if len(targets) <= MAX_DIFF_TARGETS:
        return True
    notes.append(
        f"{len(targets)} {side} persons exceed the {MAX_DIFF_TARGETS} per-person read cap; "
        f"{side} left unexplained (check --since: a wrong value empties the fold)"
    )
    return False


# Which oracle mode each mode-specific flag parameterizes. A registry rather than per-mode reject
# lists: with three modes, pairwise lists drift into silently accepting a flag that does nothing.
_MODE_FLAGS = {
    "old-pipeline": ("threshold", "warmup_sample", "no_classify"),
    "recompute": ("at", "run_id", "grace_minutes", "max_window_days", "max_oracle_members"),
    "population": ("with_ids", "max_oracle_members"),
}
_ALL_MODE_FLAGS = tuple(sorted({flag for flags in _MODE_FLAGS.values() for flag in flags}))


def _reject_flags(options: dict[str, Any], mode: str) -> None:
    """Reject mode-specific flags the active oracle does not own.

    Every mode-specific flag defaults to ``None`` (or ``False`` for a store_true) precisely so an
    explicit value that happens to equal the documented default is still caught.
    """
    owned = set(_MODE_FLAGS[mode])
    rejected = [
        f"--{flag.replace('_', '-')}"
        for flag in _ALL_MODE_FLAGS
        if flag not in owned and options[flag] is not None and options[flag] is not False
    ]
    if rejected:
        raise CommandError(f"not valid with --oracle {mode} (parameterizes another oracle): {', '.join(rejected)}")


class Command(BaseCommand):
    help = "Compare new-pipeline (shadow topic) vs an oracle (old pipeline, recompute or population) cohort membership"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--since",
            type=str,
            required=True,
            help="ISO8601 cutoff; must be the processor store-wipe time. Wrong values poison the fold and the warmup clock.",
        )
        parser.add_argument("--cohort-id", type=int, default=None, help="Limit to one cohort")
        parser.add_argument(
            "--oracle",
            choices=sorted(_MODE_FLAGS),
            default="old-pipeline",
            help="What to compare the fold against (default old-pipeline, byte-identical to prior behavior)",
        )
        parser.add_argument(
            "--with-ids",
            action="store_true",
            help="population only: carry the complete only_fold / only_legacy person-id lists in the JSON output",
        )
        parser.add_argument(
            "--at",
            type=str,
            default=None,
            help="recompute only: ISO8601 pinned instant for both the oracle window and the fold (default: the "
            "instant the drain finished); must be after --since",
        )
        parser.add_argument(
            "--run-id",
            type=str,
            default=None,
            help="recompute only: backfill run for segmentation metadata (default: latest run with a boundary)",
        )
        parser.add_argument(
            "--grace-minutes",
            type=int,
            default=None,
            help=f"recompute only: last N minutes treated as lag noise, both for a missing person's qualifying "
            f"events and for a just-entered false member (default {DEFAULT_GRACE_MINUTES})",
        )
        parser.add_argument(
            "--max-window-days",
            type=int,
            default=None,
            help=f"recompute only: cohorts whose leaf window exceeds this SKIP rather than driving an unbounded "
            f"events scan (default {DEFAULT_MAX_WINDOW_DAYS})",
        )
        parser.add_argument(
            "--max-oracle-members",
            type=int,
            default=None,
            help=f"recompute/population only: cohorts whose oracle set (leaf members / cohortpeople population) "
            f"exceeds this SKIP rather than being materialized in memory (default {DEFAULT_MAX_ORACLE_MEMBERS})",
        )
        parser.add_argument(
            "--threshold",
            type=float,
            default=None,
            help=f"old-pipeline only: max residual %% for PASS (default {DEFAULT_THRESHOLD_PCT})",
        )
        parser.add_argument(
            "--warmup-sample",
            type=int,
            default=None,
            help=f"old-pipeline only: persons sampled per cohort for the missed-emission probe over old - O; "
            f"0 skips it (default {DEFAULT_WARMUP_SAMPLE})",
        )
        parser.add_argument(
            "--no-classify",
            action="store_true",
            help="old-pipeline only: O-bounded raw diff, no R-FRESH/R-STALE rules or suspect probe",
        )
        parser.add_argument("--shadow-topic", type=str, default=DEFAULT_SHADOW_TOPIC)
        parser.add_argument("--marker-topic", type=str, default=DEFAULT_MARKER_TOPIC)
        parser.add_argument(
            "--new-kafka-hosts", type=str, default=None, help="Override bootstrap servers for both drained topics"
        )
        parser.add_argument("--security-protocol", type=str, default=None, help="Override Kafka security protocol")
        parser.add_argument("--format", choices=["table", "json"], default="table")
        parser.add_argument("--max-messages", type=int, default=None, help="Cap on shadow messages drained")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        since = _parse_since(options["since"])
        now = datetime.now(tz=UTC)
        if since >= now:
            raise CommandError("--since is in the future")
        oracle = options["oracle"]
        as_json = options["format"] == "json"
        # Validate every mode-specific flag up front: the drain below takes minutes, and a flag error
        # surfacing after it wastes the whole run.
        _reject_flags(options, oracle)
        explicit_at: Optional[datetime] = None
        team: Optional[Team] = None
        if oracle == "population":
            if options["with_ids"] and not as_json:
                raise CommandError("--with-ids needs --format json; the id lists do not fit a fixed-width table")
            if options["max_oracle_members"] is not None and options["max_oracle_members"] < 1:
                raise CommandError("--max-oracle-members must be positive")
        elif oracle == "recompute":
            self._validate_recompute_flags(options)
            if options["at"] is not None:
                explicit_at = _parse_iso_utc(options["at"], "--at")
                if explicit_at <= since:
                    raise CommandError("--at must be after --since")
                if explicit_at > now:
                    # An instant the data never reached would pin a report the run cannot describe,
                    # and would silence the staleness warning by making the skew negative.
                    raise CommandError("--at is in the future")
            # The recompute oracle needs the team tz and a resolvable run; both are cheap to check.
            team = Team.objects.filter(id=team_id).first()
            if team is None:
                raise CommandError(f"team {team_id} does not exist")
            if options["run_id"] is not None and not run_with_boundary_exists(team_id, options["run_id"]):
                raise CommandError(
                    f"--run-id {options['run_id']} is not a backfill run of team {team_id} with a boundary"
                )

        def log(message: str) -> None:
            # Keep stdout clean for the JSON document.
            (self.stderr if as_json else self.stdout).write(message)

        # 1. Universe + eligibility screen (same rows the Rust loader reads). The screen always covers
        # the whole team so cohort refs resolve, even with --cohort-id.
        cohorts = list(load_realtime_cohorts(team_id))
        if options["cohort_id"] is not None:
            if options["cohort_id"] not in {c.pk for c in cohorts}:
                raise CommandError(f"cohort {options['cohort_id']} is not a realtime cohort of team {team_id}")
            selected_ids = [options["cohort_id"]]
        else:
            selected_ids = [c.pk for c in cohorts]
        screened = screen_team({c.pk: c.filters for c in cohorts}, cascade_enabled=True)
        names = {c.pk: c.name or "Untitled" for c in cohorts}
        last_calc = {c.pk: c.last_realtime_cohort_calculation_at for c in cohorts}
        # Each cohort's legacy population was calculated on its own schedule, so the population
        # oracle's clock is per cohort — one team-wide instant cannot bound a multi-cohort fold.
        selected = set(selected_ids)
        until_by_cohort: Optional[dict[int, datetime]] = None
        pre_drain_versions: dict[int, Optional[int]] = {}
        pre_drain_calculated_at: dict[int, Optional[datetime]] = {}
        if oracle == "population":
            # A never-calculated cohort has no oracle clock, so pin its bound to --since: that
            # empties its fold instead of accumulating state the never_calculated skip row below
            # would only throw away.
            until_by_cohort = {c.pk: c.last_calculation or since for c in cohorts if c.pk in selected}
            pre_drain_versions = {c.pk: c.version for c in cohorts}
            pre_drain_calculated_at = {c.pk: c.last_calculation for c in cohorts}

        histogram = Counter(s.eligibility for s in screened.values())
        log(f"eligibility histogram (cross-check against cohort_eligibility_total): {dict(histogram)}")
        excluded = {cid: screened[cid] for cid in selected_ids if screened[cid].eligibility not in EMITTING_CLASSES}
        for cid, s in sorted(excluded.items()):
            self.stderr.write(
                self.style.WARNING(
                    f"cohort {cid} screened {s.eligibility} (drops: {', '.join(s.drop_reasons) or '-'}) — "
                    "SKIPPED. If cohort_eligibility_total shows no excluded_* classes, the screen mis-classified "
                    "it; time to build the processor /debug/catalog endpoint."
                )
            )

        # 2. New snapshot: bounded drain of the shadow topic, folded while consuming.
        config = consumer_config(
            hosts_override=options["new_kafka_hosts"],
            security_protocol_override=options["security_protocol"],
        )
        log(
            f"draining {options['shadow_topic']} and {options['marker_topic']} from {since.isoformat()} "
            f"via {config['bootstrap.servers']}"
        )
        drain_stats = DrainStats()
        # Reconcile markers ride their own topic, so completeness needs a second drain chained into
        # the same fold. Without it every cohort reads as having no complete reconcile run, and the
        # recompute and population oracles caveat their own numbers as unmeasurable.
        messages = chain(
            drain_topic(
                options["shadow_topic"],
                config=config,
                since=since,
                stats=drain_stats,
                max_messages=options["max_messages"],
            ),
            drain_topic(options["marker_topic"], config=config, since=since, stats=DrainStats()),
        )
        # An explicit --at pins the comparison clock, so the fold has to converge to that instant too.
        new_state, fold_stats = fold_membership_changes(
            messages, team_id=team_id, since=since, until=explicit_at, until_by_cohort=until_by_cohort
        )
        log(
            f"drained {drain_stats.consumed} messages from {drain_stats.partitions_read}/{drain_stats.partitions} "
            f"partitions; folded {fold_stats.folded} for team {team_id} across {len(fold_stats.cohorts_seen)} cohorts "
            f"({fold_stats.reconcile_markers_recorded} reconcile markers; "
            f"dropped: {fold_stats.dropped_wrong_team} wrong-team, {fold_stats.dropped_before_since} pre-since, "
            f"{fold_stats.dropped_after_until} post-at, "
            f"{fold_stats.dropped_malformed} malformed, {drain_stats.undecodable} undecodable; "
            f"by origin: {dict(sorted(fold_stats.folded_by_origin.items()))})"
        )

        warnings, infos = _collect_warnings(drain_stats, fold_stats.cohorts_seen - set(screened), since, now)
        for info in infos:
            self.stderr.write(info)

        # 3. Oracle-specific classification + report.
        if oracle == "recompute":
            # Stamped after the drain, not before it: the fold reflects every offset up to here, so an
            # oracle window closing earlier would score cohort entries made during the drain as hard
            # over-counts. --grace-minutes absorbs the remaining tail.
            assert team is not None  # resolved above, before the drain
            self._report_recompute(
                options=options,
                team_id=team_id,
                team=team,
                since=since,
                now=datetime.now(tz=UTC),
                explicit_at=explicit_at,
                cohorts=cohorts,
                selected_ids=selected_ids,
                screened=screened,
                names=names,
                new_state=new_state,
                fold_stats=fold_stats,
                drain_warnings=warnings,
                as_json=as_json,
                log=log,
            )
        elif oracle == "population":
            self._report_population(
                options=options,
                team_id=team_id,
                since=since,
                now=datetime.now(tz=UTC),
                selected_ids=selected_ids,
                screened=screened,
                names=names,
                pre_drain_versions=pre_drain_versions,
                pre_drain_calculated_at=pre_drain_calculated_at,
                new_state=new_state,
                fold_stats=fold_stats,
                drain_warnings=warnings,
                as_json=as_json,
                log=log,
            )
        else:
            self._report_old_pipeline(
                options=options,
                team_id=team_id,
                since=since,
                now=now,
                selected_ids=selected_ids,
                screened=screened,
                names=names,
                last_calc=last_calc,
                new_state=new_state,
                fold_stats=fold_stats,
                drain_warnings=warnings,
                as_json=as_json,
            )

    def _validate_recompute_flags(self, options: dict[str, Any]) -> None:
        grace = options["grace_minutes"]
        if grace is not None and not 0 <= grace <= MAX_GRACE_MINUTES:
            # Past a day, grace_start reaches back over the boundary day and buckets seed-day events
            # as lag noise, collapsing the whole missing set into an ungated class.
            raise CommandError(f"--grace-minutes must be between 0 and {MAX_GRACE_MINUTES}")
        for flag in ("max_window_days", "max_oracle_members"):
            if options[flag] is not None and options[flag] < 1:
                raise CommandError(f"--{flag.replace('_', '-')} must be positive")
        if options["run_id"] is not None:
            try:
                UUID(options["run_id"])
            except ValueError as err:
                # CohortBackfillRun is a UUID model; an unparseable id would otherwise surface as a
                # raw Django ValidationError traceback after the drain.
                raise CommandError(f"--run-id is not a UUID: {options['run_id']!r}") from err

    def _report_old_pipeline(
        self,
        *,
        options: dict[str, Any],
        team_id: int,
        since: datetime,
        now: datetime,
        selected_ids: list[int],
        screened: Any,
        names: dict[int, str],
        last_calc: dict[int, Any],
        new_state: Any,
        fold_stats: Any,
        drain_warnings: list[str],
        as_json: bool,
    ) -> None:
        threshold_pct = DEFAULT_THRESHOLD_PCT if options["threshold"] is None else options["threshold"]
        warmup_sample = DEFAULT_WARMUP_SAMPLE if options["warmup_sample"] is None else options["warmup_sample"]
        classifier_config = ClassifierConfig(
            since=since,
            now=now,
            threshold_pct=threshold_pct,
            warmup_sample=warmup_sample,
            classify=not options["no_classify"],
            activity_probe=make_activity_probe(team_id),
        )
        completeness_by_cohort = reconcile_completeness_by_cohort(fold_stats)
        rows: list[CohortComparison] = []
        for cid in sorted(selected_ids):
            s = screened[cid]
            old_members = load_old_membership(team_id, cid) if s.emits else set()
            rows.append(
                classify_cohort(
                    screened=s,
                    name=names[cid],
                    old_members=old_members,
                    new_state=new_state.get(cid, {}),
                    last_realtime_calculation_at=last_calc[cid],
                    config=classifier_config,
                    notes=format_reconcile_notes(completeness_by_cohort.get(cid, ())),
                )
            )

        summary = summarize(rows, config=classifier_config)
        summary.warnings.extend(drain_warnings)

        if as_json:
            # No "oracle" key here: the default path stays byte-identical to the pre-flag output.
            meta = {
                "team_id": team_id,
                "since": since.isoformat(),
                "now": now.isoformat(),
                "shadow_topic": options["shadow_topic"],
                "threshold_pct": threshold_pct,
                "warmup_sample": warmup_sample,
                "classify": not options["no_classify"],
                "caveats": list(COVERAGE_CAVEATS),
            }
            self.stdout.write(json.dumps(to_json(rows, summary, meta), indent=2))
        else:
            self.stdout.write("")
            self.stdout.write(format_table(rows))
            notes = format_notes(rows)
            if notes:
                self.stdout.write("\nnotes:\n" + notes)
            self.stdout.write("")
            self.stdout.write(format_summary(summary))
            self.stdout.write("caveats:")
            for caveat in COVERAGE_CAVEATS:
                self.stdout.write(f"  {caveat}")

        if summary.failed:
            raise CommandError(
                f"{summary.failed} eligible cohort(s) FAIL the {threshold_pct}% parity gate (residual or suspect-missing)"
            )

    def _report_population(
        self,
        *,
        options: dict[str, Any],
        team_id: int,
        since: datetime,
        now: datetime,
        selected_ids: list[int],
        screened: Mapping[int, ScreenedCohort],
        names: dict[int, str],
        pre_drain_versions: dict[int, Optional[int]],
        pre_drain_calculated_at: dict[int, Optional[datetime]],
        new_state: Any,
        fold_stats: Any,
        drain_warnings: list[str],
        as_json: bool,
        log: Any,
    ) -> None:
        with_ids: bool = options["with_ids"]
        max_members = (
            DEFAULT_MAX_ORACLE_MEMBERS if options["max_oracle_members"] is None else options["max_oracle_members"]
        )
        completeness_by_cohort = reconcile_completeness_by_cohort(fold_stats)
        # Re-read after the drain: the batch calculation is scheduled and the drain takes minutes.
        current = {
            c.pk: c
            for c in Cohort.objects.filter(team_id=team_id, pk__in=selected_ids).only(
                "id", "version", "last_calculation", "is_calculating", "deleted"
            )
        }
        log(f"diffing up to {len(selected_ids)} cohort(s) against their pinned cohortpeople population")

        rows: list[PopulationComparison] = []
        warn_states: list[PopulationCohortState] = []
        for cid in sorted(selected_ids):
            name = names[cid]
            s = screened[cid]
            if not s.emits:
                # The fold side is structurally empty because the processor never emits for this
                # cohort, so a compared row would head the table at 0% and drag the aggregate for a
                # coverage gap the eligibility histogram already reports (and the stderr warning
                # above already called SKIPPED).
                reason = "not emit-eligible: " + ", ".join(s.drop_reasons or (s.eligibility,))
                rows.append(skip_population(cohort_id=cid, name=name, reason=reason))
                continue
            cohort = current.get(cid)
            if cohort is None:
                rows.append(skip_population(cohort_id=cid, name=name, reason="cohort_row_disappeared"))
                continue
            if cohort.deleted:
                # A soft delete enqueues an async DELETE of the cohort's whole cohortpeople range
                # with no version bump, so the guard below cannot catch it and the legacy side may
                # already read back empty.
                rows.append(skip_population(cohort_id=cid, name=name, reason="deleted_during_run"))
                continue
            if cohort.version != pre_drain_versions[cid] or cohort.last_calculation != pre_drain_calculated_at[cid]:
                # Reading cohortpeople at a version that is being collapsed away would silently
                # produce a garbage row, and calculate_people_ch stamps version and last_calculation
                # in separate writes, so either moving alone means the fold's bound no longer
                # matches the population read. Re-running is the fix, so say so instead of comparing.
                rows.append(skip_population(cohort_id=cid, name=name, reason="recalculated_during_run"))
                continue
            if cohort.version is None or cohort.last_calculation is None:
                # Reading nothing would render as a clean 100% row rather than "no oracle".
                rows.append(skip_population(cohort_id=cid, name=name, reason="never_calculated"))
                continue
            if cohort.last_calculation < since:
                # The fold is bounded there, so it is empty by construction and the diff would be a
                # spurious 0%.
                rows.append(skip_population(cohort_id=cid, name=name, reason="last_calculation_before_since"))
                continue

            try:
                legacy_members = load_cohort_population(team_id, cid, cohort.version, limit=max_members)
            except OracleSetTooLarge as err:
                rows.append(skip_population(cohort_id=cid, name=name, reason=f"population_over_{err.limit}"))
                continue
            warn_states.append(
                PopulationCohortState(
                    cohort_id=cid,
                    last_calculation=cohort.last_calculation,
                    is_calculating=cohort.is_calculating,
                    has_complete_reconcile=any(run.complete for run in completeness_by_cohort.get(cid, ())),
                )
            )
            rows.append(
                compare_populations(
                    cohort_id=cid,
                    name=name,
                    fold_members=members(new_state.get(cid, {})),
                    legacy_members=legacy_members,
                    legacy_version=cohort.version,
                    calculated_at=cohort.last_calculation,
                    with_ids=with_ids,
                )
            )

        summary = summarize_population(rows)
        summary.warnings.extend(drain_warnings)
        summary.warnings.extend(_collect_population_warnings(now=now, states=warn_states))

        if as_json:
            meta = {
                "team_id": team_id,
                "since": since.isoformat(),
                "now": now.isoformat(),
                "oracle": "population",
                "with_ids": with_ids,
                "shadow_topic": options["shadow_topic"],
                "caveats": list(POPULATION_CAVEATS),
            }
            self.stdout.write(json.dumps(to_population_json(rows, summary, meta), indent=2))
            return
        self.stdout.write("")
        self.stdout.write(format_population_table(rows))
        self.stdout.write("")
        self.stdout.write(format_population_summary(summary))
        self.stdout.write("caveats:")
        for caveat in POPULATION_CAVEATS:
            self.stdout.write(f"  {caveat}")

    def _report_recompute(
        self,
        *,
        options: dict[str, Any],
        team_id: int,
        team: Team,
        since: datetime,
        now: datetime,
        explicit_at: Optional[datetime],
        cohorts: list[Any],
        selected_ids: list[int],
        screened: Any,
        names: dict[int, str],
        new_state: Any,
        fold_stats: Any,
        drain_warnings: list[str],
        as_json: bool,
        log: Any,
    ) -> None:
        at = now if explicit_at is None else explicit_at
        grace_minutes = DEFAULT_GRACE_MINUTES if options["grace_minutes"] is None else options["grace_minutes"]
        grace = timedelta(minutes=grace_minutes)
        max_window_days = DEFAULT_MAX_WINDOW_DAYS if options["max_window_days"] is None else options["max_window_days"]
        max_members = (
            DEFAULT_MAX_ORACLE_MEMBERS if options["max_oracle_members"] is None else options["max_oracle_members"]
        )
        run_id: Optional[str] = options["run_id"]

        team_tz = resolve_zoneinfo(team.timezone)
        cohort_by_id = {c.pk: c for c in cohorts}
        completeness_by_cohort = reconcile_completeness_by_cohort(fold_stats)
        log(f"recompute oracle at {at.isoformat()} (team tz {team.timezone}); grace {grace_minutes}m")

        rows: list[RecomputeComparison] = []
        warn_states: list[RecomputeCohortState] = []
        for cid in sorted(selected_ids):
            s = screened[cid]
            name = names[cid]
            reconcile_runs = completeness_by_cohort.get(cid, ())
            if not s.emits:
                reason = "not emit-eligible: " + ", ".join(s.drop_reasons or (s.eligibility,))
                rows.append(skip_comparison(cohort_id=cid, name=name, reason=reason, reconcile_runs=reconcile_runs))
                continue

            cohort = cohort_by_id[cid]
            pinned_payload, _event_names = pin_conditions_for_cohorts([cohort])
            screen = screen_for_recompute(
                cid, cohort.filters, pinned_payload["conditions"], max_window_days=max_window_days
            )
            if isinstance(screen, RecomputeUnsupported):
                rows.append(
                    skip_comparison(cohort_id=cid, name=name, reason=screen.reason, reconcile_runs=reconcile_runs)
                )
                continue

            ctx = load_run_context(team_id, cid, run_id)
            if run_id is not None and ctx is None:
                # The run itself was validated before the drain, so this cohort simply is not part of
                # it. Skipping keeps the rest of the report while refusing to claim a parity that the
                # requested run cannot segment.
                rows.append(
                    skip_comparison(
                        cohort_id=cid, name=name, reason="not_in_requested_run", reconcile_runs=reconcile_runs
                    )
                )
                continue
            warn_states.append(
                RecomputeCohortState(
                    cohort_id=cid,
                    ctx=ctx,
                    has_complete_reconcile=any(run.complete for run in reconcile_runs),
                )
            )
            if ctx is not None and ctx.run_timezone != team.timezone:
                # The processor only ever bins days in the team tz, so seed-chunk days pinned to
                # another tz cannot be attributed without shifting a day either way.
                rows.append(
                    skip_comparison(
                        cohort_id=cid, name=name, reason="run_tz_differs_from_team_tz", reconcile_runs=reconcile_runs
                    )
                )
                continue

            try:
                leaf_members = {
                    key: load_leaf_members(team_id, leaf, at=at, tz=team_tz, limit=max_members)
                    for key, leaf in screen.leaves.items()
                }
            except OracleSetTooLarge as err:
                rows.append(
                    skip_comparison(
                        cohort_id=cid, name=name, reason=f"oracle_set_over_{err.limit}", reconcile_runs=reconcile_runs
                    )
                )
                continue
            oracle_members = compute_oracle_members(screen, leaf_members)
            fold_records = new_state.get(cid, {})
            fold_members = members(fold_records)

            cohort_notes: list[str] = []
            false_targets = sorted(fold_members - oracle_members)
            missing_targets = sorted(oracle_members - fold_members)

            # Over-count split: per-leaf counts over each window slid back one day, for the false set.
            extended_leaf_counts: ExtendedLeafCounts = {}
            if false_targets and _within_target_cap(false_targets, "over-count", cohort_notes):
                extended_leaf_counts = {
                    key: load_leaf_match_counts(
                        team_id,
                        leaf,
                        person_ids=false_targets,
                        at=at,
                        tz=team_tz,
                        extra_days=EVICTION_LOOKBACK_DAYS,
                    )
                    for key, leaf in screen.leaves.items()
                }

            # Under-count segmentation: per-day counts for the missing set of a single monotone leaf.
            # `segmentation_blocker` owns whether the shape is segmentable at all; this only decides
            # whether the query is worth issuing, and reports back if the cap stopped it.
            day_counts: dict[str, list[Any]] = {}
            day_counts_loaded = True
            if missing_targets and segmentation_blocker(screen, ctx, at=at, grace=grace) is None:
                assert ctx is not None  # segmentation_blocker rejects a missing run context
                if not _within_target_cap(missing_targets, "under-count", cohort_notes):
                    day_counts_loaded = False
                else:
                    leaf = screen.sole_leaf
                    day_counts = load_day_counts(
                        team_id,
                        event_name=leaf.event_name,
                        person_ids=missing_targets,
                        scan_start=window_start_utc(at, leaf.window_days, team_tz),
                        at=at,
                        grace_start=at - grace,
                        boundary_at=ctx.boundary_at,
                        team_tz=team.timezone,
                    )

            rows.append(
                classify_recompute(
                    spec=screen,
                    name=name,
                    fold_records=fold_records,
                    oracle_members=oracle_members,
                    day_counts=day_counts,
                    extended_leaf_counts=extended_leaf_counts,
                    ctx=ctx,
                    at=at,
                    grace=grace,
                    team_tz=team_tz,
                    day_counts_loaded=day_counts_loaded,
                    reconcile_runs=reconcile_runs,
                    extra_notes=cohort_notes,
                )
            )

        summary = summarize_recompute(rows)
        summary.warnings.extend(drain_warnings)
        summary.warnings.extend(
            _collect_recompute_warnings(at=at, now=now, team_timezone=team.timezone, states=warn_states)
        )

        if as_json:
            meta = {
                "team_id": team_id,
                "since": since.isoformat(),
                "at": at.isoformat(),
                "now": now.isoformat(),
                "oracle": "recompute",
                "grace_minutes": grace_minutes,
                "run_id": run_id,
                "max_window_days": max_window_days,
                "max_oracle_members": max_members,
                "shadow_topic": options["shadow_topic"],
                "caveats": list(RECOMPUTE_CAVEATS),
            }
            self.stdout.write(json.dumps(to_recompute_json(rows, summary, meta), indent=2))
        else:
            self.stdout.write("")
            self.stdout.write(format_recompute_table(rows))
            notes = format_recompute_notes(rows)
            if notes:
                self.stdout.write("\nnotes:\n" + notes)
            self.stdout.write("")
            self.stdout.write(format_recompute_summary(summary))
            self.stdout.write("caveats:")
            for caveat in RECOMPUTE_CAVEATS:
                self.stdout.write(f"  {caveat}")

        if summary.failed:
            raise CommandError(
                f"{summary.failed} cohort(s) FAIL the recompute parity gate "
                "(hard over-count, or a seed/unseeded/post-boundary miss)"
            )
