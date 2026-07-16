"""Classified parity report: new Rust cohort pipeline vs old Temporal recompute pipeline.

Compares converged membership snapshots — the shadow topic folded to final state per
(cohort, person) vs the argMax of ClickHouse cohort_membership. The diff is bounded to
the observed universe O = persons the new pipeline decided on since the store wipe;
never-computed persons (old - O) are excluded from the gate and instead feed a separate
missed-emission probe. Divergences are classified (R-EXCLUDE / R-FRESH / R-STALE /
suspect-missing / dormant) so expected skew is separated from real bugs. Exits non-zero
if any eligible cohort FAILs the residual gate or the (sound-window) suspect-missing gate.

Run from a toolbox/web pod (needs KAFKA_INGESTION_HOSTS + the offline ClickHouse host):

    manage.py compare_cohort_membership --team-id 2 --since "2026-07-07T19:11:00Z"
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.cohorts.backend.parity.classifier import ClassifierConfig, CohortComparison, classify_cohort, summarize
from products.cohorts.backend.parity.eligibility import EMITTING_CLASSES, screen_team
from products.cohorts.backend.parity.fold import fold_membership_changes
from products.cohorts.backend.parity.kafka_io import DEFAULT_SHADOW_TOPIC, DrainStats, consumer_config, drain_topic
from products.cohorts.backend.parity.report import format_notes, format_summary, format_table, to_json
from products.cohorts.backend.parity.snapshots import load_old_membership, load_realtime_cohorts, make_activity_probe

SHADOW_TOPIC_RETENTION_DAYS = 7

# Deliberate coverage limits, restated with every report so a clean run is not over-read.
COVERAGE_CAVEATS = (
    "the diff is bounded to persons the new pipeline decided on (O); old-only persons outside O are excluded and only probed for missed emissions",
    "suspect_missing gates FAIL only where the store provably covers the window (window <= pipeline age, or property-only cohorts); on longer windows unobserved actives are unresolvable until warmup (no snapshot resolves pre-since qualifiers) and report as WARMUP",
    "minute/hour-window cohorts get suspect≈0 by construction — the probe cutoff collapses to now",
    "cohorts the old pipeline never recomputed count all only_new as fresh (residual_new is 0 there)",
    "a partial drain (poll timeout or --max-messages) understates the new side and biases toward FAIL",
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


def _parse_since(raw: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as err:
        raise CommandError(f"--since is not ISO8601: {raw!r}") from err
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class Command(BaseCommand):
    help = "Compare new-pipeline (shadow topic) vs old-pipeline (ClickHouse) cohort membership for one team"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--since",
            type=str,
            required=True,
            help="ISO8601 cutoff; must be the processor store-wipe time. Wrong values poison the fold and the warmup clock.",
        )
        parser.add_argument("--cohort-id", type=int, default=None, help="Limit to one cohort")
        parser.add_argument("--threshold", type=float, default=0.5, help="Max residual %% of union for PASS")
        parser.add_argument(
            "--warmup-sample",
            type=int,
            default=5000,
            help="Persons sampled per cohort for the missed-emission (suspect) probe over old - O; 0 skips it",
        )
        parser.add_argument(
            "--no-classify",
            action="store_true",
            help="O-bounded raw diff only, no R-FRESH/R-STALE rules or suspect probe",
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
        as_json = options["format"] == "json"

        def log(message: str) -> None:
            # Keep stdout clean for the JSON document.
            (self.stderr if as_json else self.stdout).write(message)

        # 1. Universe + eligibility screen (same rows the Rust loader reads). The screen
        # always covers the whole team so cohort refs resolve, even with --cohort-id.
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
            f"(dropped: {fold_stats.dropped_wrong_team} wrong-team, {fold_stats.dropped_before_since} pre-since, "
            f"{fold_stats.dropped_malformed} malformed, {drain_stats.undecodable} undecodable)"
        )

        warnings, infos = _collect_warnings(drain_stats, fold_stats.cohorts_seen - set(screened), since, now)
        for info in infos:
            self.stderr.write(info)

        # 3. Old snapshot + classification per eligible cohort.
        classifier_config = ClassifierConfig(
            since=since,
            now=now,
            threshold_pct=options["threshold"],
            warmup_sample=options["warmup_sample"],
            classify=not options["no_classify"],
            activity_probe=make_activity_probe(team_id),
        )
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
                )
            )

        summary = summarize(rows, config=classifier_config)
        summary.warnings.extend(warnings)

        # 4. Report.
        if as_json:
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
