# ruff: noqa: T201

"""``analyze_migration_profile`` — merge JSONL + py-spy outputs into one report.

Usage:

    python manage.py analyze_migration_profile \\
        --jsonl /tmp/migration-profile-default.jsonl \\
        --jsonl /tmp/migration-profile-posthog_db_writer.jsonl \\
        --spy   default=/tmp/migration-profile-default.spy.raw \\
        --output /tmp/migration-report.md

Each ``--spy`` entry maps a database alias to a py-spy ``--format raw`` file
emitted by ``bin/profile_migrations``. The analyze command doesn't invoke
py-spy itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from posthog.management.migration_profiling.dead_code import run_detectors
from posthog.management.migration_profiling.dead_code.parser import find_migration_files, parse_migration_file
from posthog.management.migration_profiling.dead_code.timeline import build_timeline
from posthog.management.migration_profiling.dead_code.waste_analysis import compute_alive_set, compute_waste_breakdown
from posthog.management.migration_profiling.formatters import ProfileRun, load_run, render_report
from posthog.management.migration_profiling.html_formatter import render_html_report
from posthog.management.migration_profiling.pyinstrument_parse import PyinstrumentAggregate, parse_pyinstrument_json
from posthog.management.migration_profiling.spy import SpyAggregate, aggregate_samples, parse_raw, render_flame_svg


class Command(BaseCommand):
    help = "Render a Markdown report from migration profile JSONL (and optional py-spy raw) files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--jsonl",
            action="append",
            required=True,
            metavar="PATH",
            help="Path to a profile JSONL file. Pass multiple times to merge several runs.",
        )
        parser.add_argument(
            "--spy",
            action="append",
            default=[],
            metavar="DB=PATH",
            help="py-spy raw file for a given DB alias. Pass multiple times: --spy default=/tmp/x.spy.raw",
        )
        parser.add_argument(
            "--output",
            metavar="PATH",
            default=None,
            help="Path to write the Markdown report. Defaults to stdout.",
        )
        parser.add_argument(
            "--output-html",
            metavar="PATH",
            default=None,
            help="Path to also write a rich self-contained HTML report.",
        )
        parser.add_argument(
            "--flame-svg-dir",
            metavar="DIR",
            default=None,
            help="Directory to render per-alias flame SVGs into (alongside the report).",
        )
        parser.add_argument(
            "--pyinstrument",
            action="append",
            default=[],
            metavar="DB=PATH",
            help="pyinstrument HTML report for a DB alias. Pass multiple times: --pyinstrument default=/tmp/x.html",
        )
        parser.add_argument(
            "--pyinstrument-json",
            action="append",
            default=[],
            metavar="DB=PATH",
            help="pyinstrument JSON output for a DB alias — parsed inline into the report.",
        )
        parser.add_argument(
            "--repo-root",
            metavar="PATH",
            default=".",
            help="Repo root to scan for migration files (dead-code detectors). Defaults to CWD.",
        )
        parser.add_argument(
            "--skip-dead-code",
            action="store_true",
            help="Skip dead-code detector pass (AST-walks every migration file; ~1s on PostHog).",
        )

    def handle(self, *args, **options):
        jsonl_paths = [Path(p) for p in options["jsonl"]]
        spy_entries = options.get("spy") or []
        output = options.get("output")
        flame_dir = Path(options["flame_svg_dir"]) if options.get("flame_svg_dir") else None

        runs: list[ProfileRun] = []
        for path in jsonl_paths:
            if not path.exists():
                raise CommandError(f"JSONL not found: {path}")
            runs.append(load_run(path))

        pyinstrument_entries = options.get("pyinstrument") or []
        pyinstrument_paths: dict[str, Path] = {}
        for entry in pyinstrument_entries:
            if "=" not in entry:
                raise CommandError(f"--pyinstrument expected DB=PATH, got: {entry}")
            db, p = entry.split("=", 1)
            pyinstrument_paths[db] = Path(p)

        pyinstrument_json_entries = options.get("pyinstrument_json") or []
        pyinstrument_aggregates: dict[str, PyinstrumentAggregate] = {}
        for entry in pyinstrument_json_entries:
            if "=" not in entry:
                raise CommandError(f"--pyinstrument-json expected DB=PATH, got: {entry}")
            db, p = entry.split("=", 1)
            path = Path(p)
            if not path.exists():
                raise CommandError(f"pyinstrument JSON not found: {path}")
            pyinstrument_aggregates[db] = parse_pyinstrument_json(path)

        spy_results: dict[str, tuple[SpyAggregate, Path | None]] = {}
        for entry in spy_entries:
            if "=" not in entry:
                raise CommandError(f"--spy expected DB=PATH, got: {entry}")
            db, raw_path_str = entry.split("=", 1)
            raw_path = Path(raw_path_str)
            if not raw_path.exists():
                raise CommandError(f"py-spy raw file not found: {raw_path}")
            samples = parse_raw(raw_path)
            aggregate = aggregate_samples(samples)
            svg_path = None
            if flame_dir is not None:
                flame_dir.mkdir(parents=True, exist_ok=True)
                candidate = flame_dir / f"flame-{db}.svg"
                if render_flame_svg(raw_path, candidate):
                    svg_path = candidate
                else:
                    self.stderr.write(f"Could not render flame SVG for {db} — install `flameprof` to enable.\n")
            spy_results[db] = (aggregate, svg_path)

        findings = []
        waste = None
        if not options.get("skip_dead_code"):
            repo_root = Path(options.get("repo_root") or ".").resolve()
            profile_ops = [op for run in runs for op in run.ops]
            findings = run_detectors(repo_root, profile_ops=profile_ops)
            self.stdout.write(self.style.SUCCESS(f"Dead-code detectors found {len(findings)} findings"))

            # Waste breakdown also wants the alive-set, which requires parsing
            # the migrations once. Reuse the work the runner already did under
            # the hood by re-deriving it from the same files — cheap.
            parsed = []
            for path in find_migration_files(repo_root):
                p = parse_migration_file(path)
                if p is not None:
                    parsed.append(p)
            timeline = build_timeline(parsed)
            alive = compute_alive_set(timeline)
            summaries = {k: v for run in runs for k, v in run.migration_summaries.items()}
            all_state_ops = [so for run in runs for so in run.state_ops]
            waste = compute_waste_breakdown(profile_ops, summaries, alive, state_ops=all_state_ops)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Waste analysis: {len(alive.fields)} alive fields, {len(alive.models)} alive models — "
                    f"avoidable share {waste.avoidable_share * 100:.0f}%"
                )
            )

        report = render_report(
            runs,
            spy_results,
            pyinstrument_paths=pyinstrument_paths,
            pyinstrument_aggregates=pyinstrument_aggregates,
            findings=findings,
            waste=waste,
        )

        if output:
            Path(output).write_text(report)
            self.stdout.write(self.style.SUCCESS(f"Wrote report to {output}"))
        else:
            sys.stdout.write(report)

        output_html = options.get("output_html")
        if output_html:
            html = render_html_report(
                runs,
                pyinstrument_paths=pyinstrument_paths,
                pyinstrument_aggregates=pyinstrument_aggregates,
                findings=findings,
                waste=waste,
            )
            Path(output_html).write_text(html)
            self.stdout.write(self.style.SUCCESS(f"Wrote HTML report to {output_html}"))
