from collections import namedtuple

import pytest
from unittest import mock

from _pytest.terminal import TerminalReporter

# We want the PostHog django_db_setup fixture here
from posthog.conftest import django_db_setup  # noqa: F401


def pytest_addoption(parser):
    # Example: pytest ee/hogai/eval/ci/eval_sql.py --eval churn - to only run cases containing "churn" in input
    parser.addoption("--eval", action="store")


_nodeid_to_results_url_map: dict[str, str] = {}
"""Map of test nodeid (file + test name) to Braintrust results URL."""


@pytest.fixture(scope="package")
def set_up_evals(django_db_setup):  # noqa: F811
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
