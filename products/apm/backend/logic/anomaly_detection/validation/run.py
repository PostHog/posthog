"""Bake-off report CLI.

    python -m products.apm.backend.logic.anomaly_detection.validation.run \
        --weeks 10 --eval-weeks 2 --seed 7 --out report.md

Runs every candidate band model over the same seeded scenario and prints the
precision/recall, issue-volume, persistence-ablation, and re-baseline numbers
the launch gates are tuned from.
"""

from __future__ import annotations

import os
import sys
import time
import argparse
from dataclasses import replace as dc_replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import django

import numpy as np

from products.apm.backend.logic.anomaly_detection.bands import default_band_models
from products.apm.backend.logic.anomaly_detection.baseline import TimeGrid
from products.apm.backend.logic.anomaly_detection.config import DetectionConfig
from products.apm.backend.logic.anomaly_detection.constants import BUCKETS_PER_DAY, BUCKETS_PER_WEEK
from products.apm.backend.logic.anomaly_detection.types import SeriesKey, TrafficTier
from products.apm.backend.logic.anomaly_detection.validation.harness import (
    ModelReport,
    band_calibration_sweep,
    rebaseline_experiment,
    run_model,
    silence_gate_ablation,
)
from products.apm.backend.logic.anomaly_detection.validation.simulation import (
    AnomalyKind,
    InjectedAnomaly,
    SeasonalProfile,
    SeriesSpec,
    apply_anomaly,
    build_scenario,
    generate_counts,
    inject_anomalies,
)

GRID_START = datetime(2026, 1, 5, tzinfo=UTC)  # a Monday
# US spring DST (2026-03-08) lands inside the eval window of the default
# 10-week run, so the shift-week widening is exercised, not just unit-tested.
PROJECT_TZ = ZoneInfo("America/Los_Angeles")


def _format_group_lines(report: ModelReport) -> list[str]:
    lines = []
    for (tier, severity), metrics in sorted(report.groups.items(), key=lambda kv: (kv[0][0].value, kv[0][1])):
        precision = f"{metrics.precision:.3f}" if metrics.precision is not None else "  n/a"
        recall = f"{metrics.window_recall:.3f}" if metrics.window_recall is not None else "  n/a"
        lines.append(
            f"    tier {tier.value.upper()} {severity:<6}  precision {precision}  window-recall {recall}  "
            f"tp {metrics.true_positive_buckets:>5}  fp {metrics.false_positive_buckets:>5}"
        )
    return lines


def _report_section(report: ModelReport) -> str:
    lines = [
        f"  model: {report.model_name}",
        f"    verdicts {report.verdict_count}, fp/series/day {report.false_positives_per_series_day:.3f}",
        f"    issues/day median {report.issues.median_per_day:.1f} p95 {report.issues.p95_per_day:.1f}, "
        f"issue precision {report.issues.precision if report.issues.precision is not None else float('nan'):.3f} "
        f"({report.issues.opens_in_truth}/{report.issues.opens_total})",
        f"    silence: windows {report.silence_windows_detected}/{report.silence_windows_total} detected, "
        f"fp persistent {report.silence_fp_persistent}, fp ephemeral {report.silence_fp_ephemeral}",
        *_format_group_lines(report),
    ]
    for stage, metrics in sorted(report.stage_groups.items(), key=lambda kv: kv[0].value):
        precision = f"{metrics.precision:.3f}" if metrics.precision is not None else "  n/a"
        lines.append(
            f"    stage {stage.value:<11} precision {precision}  "
            f"tp {metrics.true_positive_buckets:>5}  fp {metrics.false_positive_buckets:>5}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    # The detector itself is infra-free; only the registry-backed band models
    # (mad/zscore/iqr) sit behind posthog.tasks, which needs Django app setup.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    django.setup()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weeks", type=int, default=10)
    parser.add_argument("--eval-weeks", type=int, default=2)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--ephemerals", type=int, default=30)
    parser.add_argument("--models", nargs="*", default=None, help="subset of model names to run")
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args(argv)
    if args.weeks < 2 or not 1 <= args.eval_weeks < args.weeks:
        parser.error("--eval-weeks must be >= 1 and smaller than --weeks (>= 2)")

    config = DetectionConfig.from_env()
    grid_length = args.weeks * BUCKETS_PER_WEEK
    eval_start = grid_length - args.eval_weeks * BUCKETS_PER_WEEK
    grid = TimeGrid.build(GRID_START, grid_length, PROJECT_TZ)

    # Young services put cold-start and developing stages inside the eval
    # window; everything born at t=0 is mature by then.
    young_births = (max(0, eval_start - 5 * BUCKETS_PER_DAY), max(0, eval_start - 3 * BUCKETS_PER_WEEK))
    scenario = build_scenario(
        grid, grid_length, seed=args.seed, ephemeral_count=args.ephemerals, young_births=young_births
    )
    rng = np.random.default_rng(args.seed + 1)
    inject_anomalies(scenario, rng, eval_start, grid_length)

    models = default_band_models(rate_floor=config.band_rate_floor, dispersion_floor=config.dispersion_floor)
    if args.models:
        known = {m.name for m in models}
        unknown = sorted(set(args.models) - known)
        if unknown:
            parser.error(f"unknown model(s): {', '.join(unknown)}; choose from: {', '.join(sorted(known))}")
        models = [m for m in models if m.name in args.models]

    out = [
        "# Anomaly detector bake-off",
        f"seed={args.seed} weeks={args.weeks} eval_weeks={args.eval_weeks} "
        f"series={len(scenario.specs)} anomalies={len(scenario.anomalies)}",
        "",
        "## Band model bake-off",
        "```",
    ]
    reports = {}
    for model in models:
        started = time.monotonic()
        report = run_model(scenario, grid, config, model, eval_start, grid_length)
        reports[model.name] = report
        out.append(_report_section(report))
        out.append(f"    ({time.monotonic() - started:.1f}s)")
        out.append("")
        print(out[-3], file=sys.stderr)  # noqa: T201

    # Defaults ship without severity widening (NB measures dispersion itself);
    # quantify what the multiplier mechanism would do to NB for the record.
    nb = next((m for m in models if m.name == "negative_binomial"), None)
    if nb is not None:
        widened = dc_replace(config, severity_variance_multipliers={"error": 4.0, "fatal": 4.0, "warn": 1.5})
        report = run_model(scenario, grid, widened, nb, eval_start, grid_length)
        report.model_name = "negative_binomial (with severity widening)"
        out.append(_report_section(report))
        out.append("")
    out.append("```")

    sweep = band_calibration_sweep(models, config.alpha_per_bucket, seed=args.seed + 3)
    out += [
        "",
        f"## Band calibration sweep (clean NB data; calibrated ~= 2*alpha = {2 * config.alpha_per_bucket:.1e})",
        "```",
    ]
    for model in models:
        out.append(f"  {model.name}")
        for cv in sorted({c.cv for c in sweep}):
            cells = sorted((c for c in sweep if c.model_name == model.name and c.cv == cv), key=lambda c: c.lam)
            rates = "  ".join(f"lam={c.lam:>6.0f}: {c.false_positive_rate:.4f}" for c in cells)
            out.append(f"    cv={cv:<5} {rates}")
    out.append("```")

    # Gate and re-baseline experiments measure baseline/gate behavior, so they
    # need a calibrated band model under them — a miscalibrated one (Poisson on
    # overdispersed data) fires constantly and swamps the effect being measured.
    ablation_model = next((m for m in models if m.name == "negative_binomial"), models[0])
    ablation = silence_gate_ablation(scenario, grid, config, ablation_model, eval_start, grid_length)
    out += ["", f"## Persistence gate ablation ({ablation_model.name})", "```"]
    for label, report in ablation.items():
        out.append(
            f"  {label:<28} silence fp ephemeral {report.silence_fp_ephemeral:>4}, "
            f"persistent {report.silence_fp_persistent:>4}, opens/day median {report.issues.median_per_day:.1f}"
        )
    out.append("```")

    # Dedicated longer timeline: the passive re-baseline claim is ~4 weeks, so
    # the shift needs >4 weeks of runway regardless of the bake-off's --weeks.
    shift_weeks = 12
    shift_grid_length = shift_weeks * BUCKETS_PER_WEEK
    shift_grid = TimeGrid.build(GRID_START, shift_grid_length, ZoneInfo("UTC"))
    shift_spec = SeriesSpec(
        key=SeriesKey(namespace="default", service="svc-shift", environment="production", severity="info"),
        tier=TrafficTier.A,
        profile=SeasonalProfile.DIURNAL,
        mean_per_bucket=1_500.0,
        cv=0.12,
    )
    shift_index = 7 * BUCKETS_PER_WEEK
    out += ["", "## Level shift re-baselining (permanent shift, 5 weeks runway)", "```"]
    # x2 sits inside the level-factor clamp (absorbed by the level component);
    # x4 exceeds it and exercises the exclusion-cap path the claim is about.
    for factor in (2.0, 4.0):
        shift_rng = np.random.default_rng(args.seed + 2)
        shift_counts = generate_counts(shift_spec, shift_grid, shift_rng)
        shift = InjectedAnomaly(shift_spec.key, AnomalyKind.LEVEL_SHIFT, shift_index, shift_grid_length, factor)
        apply_anomaly(shift_counts, shift)
        for label, stability in (("passive (exclusion cap)", None), ("stability test (12 buckets)", 12)):
            result = rebaseline_experiment(
                shift_spec,
                shift_counts,
                shift_grid,
                config,
                ablation_model,
                shift_index,
                shift_grid_length,
                stability_buckets=stability,
            )
            days = f"{result.days_to_quiet:.1f} days" if result.days_to_quiet is not None else "still firing at run end"
            out.append(f"  x{factor:.0f} {label:<28} {days} ({result.verdicts_emitted} verdicts)")
    out.append("```")

    text = "\n".join(out)
    print(text)  # noqa: T201
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
