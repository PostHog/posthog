import asyncio
import os
from collections import namedtuple
from collections.abc import Sequence
from unittest import mock

import pytest
from _pytest.terminal import TerminalReporter
from braintrust import EvalAsync, Metadata, init_logger
from braintrust.framework import EvalData, EvalScorer, EvalTask, Input, Output
from braintrust_langchain import BraintrustCallbackHandler, set_global_handler

# We want the PostHog django_db_setup fixture here
from posthog.conftest import django_db_setup  # noqa: F401

handler = BraintrustCallbackHandler()
if os.environ.get("BRAINTRUST_API_KEY"):
    set_global_handler(handler)


def pytest_addoption(parser):
    # Example: pytest ee/hogai/eval/ci/eval_sql.py --eval churn - to only run cases containing "churn" in input
    parser.addoption("--eval", action="store")


async def MaxEval(
    experiment_name: str,
    data: EvalData[Input, Output],
    task: EvalTask[Input, Output],
    scores: Sequence[EvalScorer[Input, Output]],
    pytestconfig: pytest.Config,
    metadata: Metadata | None = None,
):
    # We need to specify a separate project for each MaxEval() suite for comparison to baseline to work
    # That's the way Braintrust folks recommended - Braintrust projects are much more lightweight than PostHog ones
    project_name = f"max-ai-{experiment_name}"
    init_logger(project_name)

    # Filter by --case <eval_case_name_part> pytest flag
    case_filter = pytestconfig.option.eval
    if case_filter:
        if asyncio.iscoroutine(data):
            data = await data
        data = [case for case in data if case_filter in str(case.input)]  # type: ignore

    result = await EvalAsync(
        project_name,
        data=data,
        task=task,
        scores=scores,
        trial_count=3 if os.getenv("CI") else 1,
        timeout=60 * 8,
        max_concurrency=20,
        is_public=True,
        metadata=metadata,
    )
    if os.getenv("EXPORT_EVAL_RESULTS"):
        with open("eval_results.jsonl", "a") as f:
            f.write(result.summary.as_json() + "\n")
    return result


_nodeid_to_results_url_map: dict[str, str] = {}
"""Map of test nodeid (file + test name) to Braintrust results URL."""


@pytest.fixture(scope="package")
def setup_evals(django_db_setup):  # noqa: F811
    yield


@pytest.fixture(autouse=True)
def capture_stdout(request, capsys):
    yield
    captured = capsys.readouterr()
    if "See results for " in captured.out:
        # Get only the line with the results link. The output we are extracting from is something like this:
        # [...]
        # 0.00$ (-00.02%) 'estimated_cost'        (4 improvements, 3 regressions)
        # See results for braintrust-more-evals-1747934384 at https://www.braintrust.dev/app/PostHog/p/max-ai-memory/experiments/braintrust-more-evals-1747934384
        # Experiment braintrust-more-evals-1747934384 is running at https://www.braintrust.dev/app/PostHog/p/max-ai-memory/experiments/braintrust-more-evals-1747934384
        # [...]
        results_url = next(line for line in captured.out.split("\n") if "See results for " in line).split(" at ")[1]
        _nodeid_to_results_url_map[request.node.nodeid] = results_url


class BraintrustURLReporter(TerminalReporter):  # type: ignore
    """
    Our reporter adds one feature to the default one: for each passed eval_ test, it adds a link to the Braintrust results.
    By default, passed tests don't get any short summary, but we can override that - which is what we do here.
    """

    # No idea what type report.longrepr or report.longrrepr.reprcrash _should_ be, but this works
    DummyLongRepr = namedtuple("DummyLongRepr", ["reprcrash"])
    DummyReprCrash = namedtuple("DummyReprCrash", ["message"])

    def short_test_summary(self):
        for report in self.stats.get("passed", []):
            report.longrepr = self.DummyLongRepr(
                reprcrash=self.DummyReprCrash(
                    message=_nodeid_to_results_url_map.get(report.nodeid, f"No Braintrust results for {report.nodeid}")
                )
            )
        with mock.patch("_pytest.terminal.running_on_ci", return_value=True):
            # Make pytest think we're running in CI, because annoyingly _pytest.terminal._get_line_with_reprcrash_message
            # trims the short test summary (i.e. Braintrust URL) terminal width if it thinks we're not in CI
            super().short_test_summary()


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    if not str(config.rootdir).endswith("/ee/hogai/eval"):
        return  # No-op if not running specifically evals
    # Register a custom reporter that adds a link to the Braintrust results
    vanilla_reporter = config.pluginmanager.getplugin("terminalreporter")
    braintrust_url_reporter = BraintrustURLReporter(config)
    config.pluginmanager.unregister(vanilla_reporter)
    config.pluginmanager.register(braintrust_url_reporter, "terminalreporter")
