from collections import Counter
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team

from products.actions.backend.selector_audit.audit import (
    ACTIONABLE_BUCKETS,
    BUCKET_DEPLOY_DAY_REWRITE,
    BUCKET_SAFE_REWRITE,
    apply_rewrites,
    build_report,
    carry_over_previous,
    collect_references,
    count_autocapture_events,
    decide_bucket,
    detect_live_compiler,
    diff_reports,
    discover_rows,
    load_report,
    measure_team_rows,
    prefill_counts_from_previous,
    save_report,
)


class Command(BaseCommand):
    help = (
        "Audit action selectors ahead of the selector compiler change (PR #80653). "
        "Classifies every selector, optionally measures old-vs-new match counts over recent "
        "$autocapture events, buckets each selector, and can apply measured-safe '>'-to-space "
        "rewrites. Read-only unless --live-run is passed."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-ids", nargs="+", type=int, help="Limit to these team IDs (default: all teams)")
        parser.add_argument("--measure", action="store_true", help="Run ClickHouse match counts per selector")
        parser.add_argument("--days", type=int, default=7, help="Days of $autocapture to measure over (default 7)")
        parser.add_argument(
            "--tolerance",
            type=float,
            default=0.02,
            help="Relative difference under which two match counts are the same (default 0.02)",
        )
        parser.add_argument(
            "--rewrite-gain-tolerance",
            type=float,
            default=0.1,
            help="How much a rewrite may gain over the old count and still be faithful (default 0.1)",
        )
        parser.add_argument("--batch-size", type=int, default=40, help="Selectors per ClickHouse query (default 40)")
        parser.add_argument("--sleep", type=float, default=1.0, help="Seconds between ClickHouse queries (default 1.0)")
        parser.add_argument(
            "--resume",
            action="store_true",
            help="With --measure: keep counts already in the report at --output and only measure the rest",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="action_selector_audit.json",
            help="Report path; re-runs update it in place and print a diff (CSV written alongside)",
        )
        parser.add_argument("--skip-references", action="store_true", help="Skip the referencing-objects lookup")
        parser.add_argument(
            "--apply-safe-rewrites",
            action="store_true",
            help="Apply rewrites in the safe_rewrite bucket (dry-run without --live-run)",
        )
        parser.add_argument(
            "--apply-deploy-day-rewrites",
            action="store_true",
            help="Apply deploy_day_rewrite rewrites; refuses unless the live compiler is the new one",
        )
        parser.add_argument("--live-run", action="store_true", help="Actually write; default is dry-run")

    def handle(self, *args: Any, **options: Any) -> None:
        log = self.stdout.write
        output_path = Path(options["output"])
        applying = options["apply_safe_rewrites"] or options["apply_deploy_day_rewrites"]
        if options["live_run"] and not applying:
            raise CommandError("--live-run does nothing without --apply-safe-rewrites/--apply-deploy-day-rewrites")
        if options["resume"] and not options["measure"]:
            raise CommandError("--resume only applies with --measure")

        live_compiler = detect_live_compiler()
        log(f"live compiler: {live_compiler}")
        if live_compiler == "unknown":
            log(
                self.style.WARNING(
                    "the in-repo compiler matches neither vendored copy; counts may not reflect production"
                )
            )
        if applying and live_compiler == "unknown":
            raise CommandError("refusing to apply rewrites: live compiler is neither the old nor the new one")
        if options["apply_deploy_day_rewrites"] and live_compiler != "new":
            raise CommandError(
                "refusing --apply-deploy-day-rewrites: the live compiler is still the old one; "
                "these rewrites only become faithful once PR #80653 is deployed"
            )

        previous = load_report(output_path)
        rows = discover_rows(options["team_ids"])
        log(f"discovered {len(rows)} selector steps across {len({row['team_id'] for row in rows})} teams")
        if not rows:
            return

        team_ids = sorted({row["team_id"] for row in rows})
        team_totals: dict[int, Any] = {}
        run_params: dict[str, Any] = {
            "days": options["days"],
            "tolerance": options["tolerance"],
            "rewrite_gain_tolerance": options["rewrite_gain_tolerance"],
            "measured": options["measure"],
            "team_ids": options["team_ids"],
        }
        if options["measure"]:
            if options["resume"]:
                resumed = prefill_counts_from_previous(rows, previous)
                log(f"resume: reusing counts for {resumed} of {len(rows)} selector steps from {output_path}")

            def checkpoint() -> None:
                # Persist progress after every batch, so a killed run loses at
                # most one batch and can restart with --resume.
                for checkpoint_row in rows:
                    decide_bucket(checkpoint_row, options["tolerance"], options["rewrite_gain_tolerance"])
                save_report(output_path, build_report(rows, team_totals, run_params, live_compiler))

            for team_id in team_ids:
                team_rows = [row for row in rows if row["team_id"] == team_id]
                total = count_autocapture_events(team_id, options["days"])
                team_totals[team_id] = total
                if total == 0:
                    log(f"team {team_id}: no $autocapture in the last {options['days']} days, skipping measurement")
                    continue
                log(f"team {team_id}: measuring {len(team_rows)} selector steps against {total} autocapture events")
                measure_team_rows(
                    team_id,
                    team_rows,
                    options["days"],
                    options["batch_size"],
                    options["sleep"],
                    log,
                    on_batch_done=checkpoint,
                )
            for row in rows:
                decide_bucket(row, options["tolerance"], options["rewrite_gain_tolerance"])

        carry_over_previous(rows, previous, keep_measurements=not options["measure"])

        if not options["skip_references"]:
            teams_by_id = {team.pk: team for team in Team.objects.filter(id__in=team_ids)}
            for team_id in team_ids:
                team = teams_by_id.get(team_id)
                if team is None:
                    continue
                collect_references(team, [row for row in rows if row["team_id"] == team_id], log)

        if applying:
            buckets = set()
            if options["apply_safe_rewrites"]:
                buckets.add(BUCKET_SAFE_REWRITE)
            if options["apply_deploy_day_rewrites"]:
                buckets.add(BUCKET_DEPLOY_DAY_REWRITE)
            summary = apply_rewrites(rows, frozenset(buckets), options["live_run"], log)
            if options["live_run"]:
                log(self.style.SUCCESS(f"applied {summary['applied']} rewrites, skipped {summary['skipped']}"))
            else:
                log(
                    f"dry-run: {summary['planned']} rewrites would be applied "
                    f"({summary['skipped']} skipped); pass --live-run to write"
                )

        diff = diff_reports(previous, rows)
        report = build_report(rows, team_totals, run_params, live_compiler)
        csv_path = save_report(output_path, report)

        buckets_histogram = Counter(row["bucket"] for row in rows)
        log("bucket summary: " + ", ".join(f"{bucket}={count}" for bucket, count in sorted(buckets_histogram.items())))
        actionable = [row for row in rows if row["bucket"] in ACTIONABLE_BUCKETS]
        for row in actionable:
            log(
                f"  [{row['bucket']}] team {row['team_id']} action {row['action_id']} "
                f"step {row['step_index']}: {row['selector']!r} "
                f"old={row['counts']['old_original']} new={row['counts']['new_original']}"
            )
        if previous:
            log(
                f"diff vs previous report: {len(diff['fixed'])} fixed, "
                f"{len(diff['still_open'])} still open, {len(diff['new'])} new"
            )
            for key in diff["fixed"]:
                log(f"  fixed: {key}")
            for key in diff["new"]:
                log(f"  new: {key}")
        log(f"report written to {output_path} and {csv_path}")
