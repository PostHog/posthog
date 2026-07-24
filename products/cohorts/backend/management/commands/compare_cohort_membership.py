"""Classified parity report: new Rust cohort pipeline vs an oracle.

Two oracle modes select what the folded shadow topic (the new pipeline's converged membership) is
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

Run from a toolbox/web pod (needs KAFKA_INGESTION_HOSTS + the offline ClickHouse host):

    manage.py compare_cohort_membership --team-id 2 --since "2026-07-07T19:11:00Z"
    manage.py compare_cohort_membership --team-id 2 --cohort-id 433564 --since "2026-07-24T02:00:00Z" --oracle recompute
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team.team import Team

from products.cohorts.backend.backfill.pinning import pin_conditions_for_cohorts
from products.cohorts.backend.parity.classifier import ClassifierConfig, CohortComparison, classify_cohort, summarize
from products.cohorts.backend.parity.eligibility import EMITTING_CLASSES, screen_team
from products.cohorts.backend.parity.fold import fold_membership_changes, members, reconcile_completeness_by_cohort
from products.cohorts.backend.parity.kafka_io import DEFAULT_SHADOW_TOPIC, DrainStats, consumer_config, drain_topic
from products.cohorts.backend.parity.oracle import load_day_counts, load_leaf_members, load_run_context
from products.cohorts.backend.parity.recompute import (
    RecomputeComparison,
    RecomputeUnsupported,
    RunContext,
    classify_recompute,
    compute_oracle_members,
    screen_for_recompute,
    skip_comparison,
    summarize_recompute,
)
from products.cohorts.backend.parity.report import (
    format_notes,
    format_recompute_notes,
    format_recompute_summary,
    format_recompute_table,
    format_reconcile_notes,
    format_summary,
    format_table,
    to_json,
    to_recompute_json,
)
from products.cohorts.backend.parity.snapshots import load_old_membership, load_realtime_cohorts, make_activity_probe
from products.cohorts.backend.parity.tzdates import day_of_instant, resolve_zoneinfo, start_of_day_utc

SHADOW_TOPIC_RETENTION_DAYS = 7
# The fold (drained ≈ now) sees a later processor state than an oracle window ending well before now.
RECOMPUTE_STALE_AT_MINUTES = 15

# Deliberate coverage limits, restated with every report so a clean run is not over-read.
COVERAGE_CAVEATS = (
    "the diff is bounded to persons the new pipeline decided on (O); old-only persons outside O are excluded and only probed for missed emissions",
    "suspect_missing gates FAIL only where the store provably covers the window (window <= pipeline age, or property-only cohorts); on longer windows unobserved actives are unresolvable until warmup (no snapshot resolves pre-since qualifiers) and report as WARMUP",
    "minute/hour-window cohorts get suspect≈0 by construction — the probe cutoff collapses to now",
    "cohorts the old pipeline never recomputed count all only_new as fresh (residual_new is 0 there)",
    "a partial drain (poll timeout or --max-messages) understates the new side and biases toward FAIL",
)

RECOMPUTE_CAVEATS = (
    "the oracle reproduces only performed_event / performed_event_multiple leaves with a string event key, no event_filters (property matching is HogVM bytecode, not SQL), and whole-day sliding windows; everything else SKIPs",
    "over-count (false_members) is the hard gate; a pending-eviction share near team-tz midnight is sweep lag, reported but not gated",
    "under-count segmentation needs a single supported leaf and a monotone op (gte/gt); multi-leaf, non-monotone, or no-run cohorts report membership parity only (missing left unsegmented)",
    "missing_boundary_day is the expected decaying gap; missing_seed_domain and missing_unseeded_day gate FAIL",
    "the window uses the current team tz; day-domain attribution uses the run tz — a mismatch warns",
    "override/merge drift (fold ids resolved at processing time vs the oracle's current overrides) can pair a false_member with a missing person; both sets ship in the JSON for triage",
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
            f"--at is {int(stale.total_seconds() // 60)}m before now; the fold reflects a later processor "
            "state than the oracle window"
        )
    for state in states:
        if state.ctx is None:
            warnings.append(
                f"cohort {state.cohort_id}: no backfill run with a boundary; the missing set is left unsegmented"
            )
            continue
        if state.ctx.run_timezone != team_timezone:
            warnings.append(
                f"cohort {state.cohort_id}: run tz {state.ctx.run_timezone} != team tz {team_timezone}; the "
                "window uses team tz while day-domain attribution uses run tz"
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


class Command(BaseCommand):
    help = "Compare new-pipeline (shadow topic) vs an oracle (old pipeline or recompute) cohort membership"

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
            choices=["old-pipeline", "recompute"],
            default="old-pipeline",
            help="What to compare the fold against (default old-pipeline, byte-identical to prior behavior)",
        )
        parser.add_argument(
            "--at",
            type=str,
            default=None,
            help="recompute only: ISO8601 pinned instant for the oracle window (default now); must be after --since",
        )
        parser.add_argument(
            "--run-id",
            type=str,
            default=None,
            help="recompute only: backfill run for segmentation metadata (default: latest run with a boundary)",
        )
        parser.add_argument(
            "--grace-minutes", type=int, default=10, help="recompute only: last N minutes treated as lag noise"
        )
        parser.add_argument("--threshold", type=float, default=0.5, help="old-pipeline only: max residual %% for PASS")
        parser.add_argument(
            "--warmup-sample",
            type=int,
            default=5000,
            help="old-pipeline only: persons sampled per cohort for the missed-emission probe over old - O; 0 skips it",
        )
        parser.add_argument(
            "--no-classify",
            action="store_true",
            help="old-pipeline only: O-bounded raw diff, no R-FRESH/R-STALE rules or suspect probe",
        )
        parser.add_argument("--shadow-topic", type=str, default=DEFAULT_SHADOW_TOPIC)
        parser.add_argument("--new-kafka-hosts", type=str, default=None, help="Override shadow-topic bootstrap servers")
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
        if oracle == "recompute":
            self._reject_old_pipeline_flags(options)

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
        log(f"draining {options['shadow_topic']} from {since.isoformat()} via {config['bootstrap.servers']}")
        drain_stats = DrainStats()
        messages = drain_topic(
            options["shadow_topic"],
            config=config,
            since=since,
            stats=drain_stats,
            max_messages=options["max_messages"],
        )
        new_state, fold_stats = fold_membership_changes(messages, team_id=team_id, since=since)
        log(
            f"drained {drain_stats.consumed} messages from {drain_stats.partitions_read}/{drain_stats.partitions} "
            f"partitions; folded {fold_stats.folded} for team {team_id} across {len(fold_stats.cohorts_seen)} cohorts "
            f"({fold_stats.reconcile_markers_recorded} reconcile markers; "
            f"dropped: {fold_stats.dropped_wrong_team} wrong-team, {fold_stats.dropped_before_since} pre-since, "
            f"{fold_stats.dropped_malformed} malformed, {drain_stats.undecodable} undecodable; "
            f"by origin: {dict(sorted(fold_stats.folded_by_origin.items()))})"
        )

        warnings, infos = _collect_warnings(drain_stats, fold_stats.cohorts_seen - set(screened), since, now)
        for info in infos:
            self.stderr.write(info)

        # 3. Oracle-specific classification + report.
        if oracle == "recompute":
            self._report_recompute(
                options=options,
                team_id=team_id,
                since=since,
                now=now,
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

    def _reject_old_pipeline_flags(self, options: dict[str, Any]) -> None:
        rejected: list[str] = []
        if options["threshold"] != 0.5:
            rejected.append("--threshold")
        if options["warmup_sample"] != 5000:
            rejected.append("--warmup-sample")
        if options["no_classify"]:
            rejected.append("--no-classify")
        if rejected:
            raise CommandError(
                f"{', '.join(rejected)} parameterize the old-pipeline classifier and are not valid with --oracle recompute"
            )

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
        classifier_config = ClassifierConfig(
            since=since,
            now=now,
            threshold_pct=options["threshold"],
            warmup_sample=options["warmup_sample"],
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
                "threshold_pct": options["threshold"],
                "warmup_sample": options["warmup_sample"],
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
                f"{summary.failed} eligible cohort(s) FAIL the {options['threshold']}% parity gate (residual or suspect-missing)"
            )

    def _report_recompute(
        self,
        *,
        options: dict[str, Any],
        team_id: int,
        since: datetime,
        now: datetime,
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
        at = now if options["at"] is None else _parse_iso_utc(options["at"], "--at")
        if at <= since:
            raise CommandError("--at must be after --since")

        team = Team.objects.get(id=team_id)
        team_tz = resolve_zoneinfo(team.timezone)
        cohort_by_id = {c.pk: c for c in cohorts}
        completeness_by_cohort = reconcile_completeness_by_cohort(fold_stats)
        log(f"recompute oracle at {at.isoformat()} (team tz {team.timezone}); grace {options['grace_minutes']}m")

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
            screen = screen_for_recompute(cid, cohort.filters, pinned_payload["conditions"])
            if isinstance(screen, RecomputeUnsupported):
                rows.append(
                    skip_comparison(cohort_id=cid, name=name, reason=screen.reason, reconcile_runs=reconcile_runs)
                )
                continue

            ctx = load_run_context(team_id, cid, options["run_id"])
            seg_tz_name = ctx.run_timezone if ctx else team.timezone
            seg_tz = resolve_zoneinfo(seg_tz_name)

            leaf_members = {h: load_leaf_members(team_id, leaf, at=at, tz=team_tz) for h, leaf in screen.leaves.items()}
            oracle_members = compute_oracle_members(screen, leaf_members)
            fold_members = members(new_state.get(cid, {}))

            day_counts: dict[str, list[Any]] = {}
            if screen.single_leaf:
                targets = list(oracle_members ^ fold_members)  # missing ∪ false_members
                if targets:
                    leaf = screen.sole_leaf
                    at_day = day_of_instant(at, seg_tz)
                    scan_start = start_of_day_utc(at_day - timedelta(days=leaf.window_days + 1), seg_tz)
                    grace_start = at - timedelta(minutes=options["grace_minutes"])
                    boundary_at = ctx.boundary_at if ctx else at
                    day_counts = load_day_counts(
                        team_id,
                        event_name=leaf.event_name,
                        person_ids=targets,
                        scan_start=scan_start,
                        at=at,
                        grace_start=grace_start,
                        boundary_at=boundary_at,
                        seg_tz=seg_tz_name,
                    )

            rows.append(
                classify_recompute(
                    spec=screen,
                    name=name,
                    fold_members=fold_members,
                    oracle_members=oracle_members,
                    day_counts=day_counts,
                    ctx=ctx,
                    at=at,
                    seg_tz=seg_tz,
                    reconcile_runs=reconcile_runs,
                )
            )
            warn_states.append(
                RecomputeCohortState(
                    cohort_id=cid,
                    ctx=ctx,
                    has_complete_reconcile=any(run.complete for run in reconcile_runs),
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
                "grace_minutes": options["grace_minutes"],
                "run_id": options["run_id"],
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
                f"{summary.failed} cohort(s) FAIL the recompute parity gate (hard over-count or seed/unseeded miss)"
            )
