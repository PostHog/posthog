"""
Dashboards v2 before/after scorecard. See README.md.

    DEBUG=1 PYTHONPATH=. DJANGO_SETTINGS_MODULE=posthog.settings \
        python products/dashboards/backend/benchmarks/dashboard_v2_scorecard.py --out /tmp/dv2.json

Runs every scenario with `dashboard-v2` forced off, then forced on, and writes one JSON scorecard plus a
markdown table (also printed). The scenarios need a Django test database, so this runs them through
pytest against `test_<POSTHOG_DB_NAME>` (default `test_posthog_dv2bench`, created on first run).
"""

import os
import sys
import json
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
DEFAULT_DB_NAME = "posthog_dv2bench"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", help="write the JSON scorecard here")
    p.add_argument("--md-out", help="write the markdown table here (default: next to --out, .md)")
    p.add_argument(
        "--dashboard-v2",
        choices=["off", "on", "both"],
        default="both",
        help="which arm to run: off (today), on (forced through POSTHOG_FEATURE_FLAGS_FORCE_ENABLED), or both",
    )
    p.add_argument("--quick", action="store_true", help="short windows, one run per arm (about 3 min)")
    p.add_argument("--repeats", type=int, help="runs per arm, for run-to-run noise (default 3, quick 1)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--scenarios", default="ABCDE", help="subset to run, e.g. BC")
    p.add_argument("--duration", type=float, help="seconds of auto refresh in scenario A (default 120)")
    p.add_argument(
        "--measure-unmerged",
        action="store_true",
        help="also run the flag-on arm for steps whose code isn't on this branch (it should match before)",
    )
    args = p.parse_args()

    config: dict[str, object] = {
        "quick": args.quick,
        "seed": args.seed,
        "arms": ["off", "on"] if args.dashboard_v2 == "both" else [args.dashboard_v2],
        "scenarios": list(args.scenarios.upper()),
        "measure_unmerged": args.measure_unmerged,
    }
    if args.repeats is not None:
        config["repeats"] = args.repeats
    if args.duration is not None:
        config["refresh_duration_s"] = args.duration

    md_out = args.md_out or (str(Path(args.out).with_suffix(".md")) if args.out else None)
    env = os.environ
    env["RUN_DASHBOARD_V2_BENCH"] = "1"
    env["DASHBOARD_V2_BENCH_CONFIG"] = json.dumps(config)
    if args.out:
        env["DASHBOARD_V2_BENCH_OUT"] = str(Path(args.out).resolve())
    if md_out:
        env["DASHBOARD_V2_BENCH_MD_OUT"] = str(Path(md_out).resolve())
    # DEBUG settings read the database name from PGDATABASE; pytest-django prefixes it with test_.
    env.setdefault("PGDATABASE", env.get("POSTHOG_DB_NAME", DEFAULT_DB_NAME))

    os.chdir(REPO_ROOT)
    import pytest  # noqa: PLC0415 — pytest-django must configure Django before anything imports it

    return pytest.main(
        [
            str(HERE / "test_dashboard_v2_scorecard.py"),
            "-q",
            "-s",
            "-p",
            "no:cacheprovider",
            "--reuse-db",
        ]
    )


if __name__ == "__main__":
    sys.exit(main())
