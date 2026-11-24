import os
import sys

import pytest

from products.dashboards.backend.benchmarks.scorecard_scenarios import (
    NOT_MERGED,
    config_from_env,
    real_redis,
    run_scorecard,
    write_outputs,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DASHBOARD_V2_BENCH") != "1",
    reason="benchmark: set RUN_DASHBOARD_V2_BENCH=1, or run dashboard_v2_scorecard.py",
)


def _log(line: str) -> None:
    sys.stderr.write(line + "\n")


@pytest.mark.django_db(transaction=True)
def test_dashboard_v2_scorecard() -> None:
    cfg = config_from_env()
    with real_redis():
        scorecard = run_scorecard(cfg, log=_log)
    markdown = write_outputs(
        scorecard, os.environ.get("DASHBOARD_V2_BENCH_OUT"), os.environ.get("DASHBOARD_V2_BENCH_MD_OUT")
    )
    sys.stdout.write("\n" + markdown)

    assert [s["id"] for s in scorecard["scenarios"]] == list(cfg.scenarios)
    for scenario in scorecard["scenarios"]:
        for metric in scenario["metrics"]:
            if "off" in cfg.arms:
                assert len(metric["before_runs"]) == cfg.repeats, (scenario["id"], metric["name"])
            if "on" in cfg.arms and NOT_MERGED not in scenario["after_status"]:
                assert len(metric["after_runs"]) == cfg.repeats, (scenario["id"], metric["name"])
