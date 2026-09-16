from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

import pytest

from _pytest._io import TerminalWriter
from _pytest.terminal import TerminalReporter

from posthog.conftest import _JUnitTimingsPlugin
from posthog.test.junit import set_junit_report_location


def test_junit_report_uses_the_collected_test_file() -> None:
    report = pytest.TestReport(
        nodeid="posthog/api/test/test_project.py::TestProjectAPI::test_delete_project",
        location=("../../../../python/unittest/mock.py", 1426, "test_delete_project"),
        keywords={},
        outcome="passed",
        longrepr=None,
        when="call",
    )
    item = SimpleNamespace(
        path=Path("/repo/posthog/api/test/test_project.py"),
        config=SimpleNamespace(rootpath=Path("/repo")),
    )

    set_junit_report_location(cast(pytest.Item, item), report)

    assert report.location == ("posthog/api/test/test_project.py", 1426, "test_delete_project")


@pytest.mark.parametrize("when", ["setup", "call", "teardown"])
def test_retry_diagnostics_survive_a_passing_final_attempt(
    monkeypatch: pytest.MonkeyPatch, when: Literal["setup", "call", "teardown"]
) -> None:
    monkeypatch.setenv("RUNNER_NAME", "runner-example")
    plugin = _JUnitTimingsPlugin()
    recovered = pytest.TestReport(
        nodeid="test_example.py::test_retry",
        location=("test_example.py", 1, "test_retry"),
        keywords={},
        outcome="passed",
        longrepr=None,
        when="teardown",
        rerun=1,
    )
    plugin.pytest_runtest_logreport(recovered)
    assert dict(recovered.user_properties) == {"posthog.reruns": "1", "posthog.runner_name": "runner-example"}

    failed_attempt = pytest.TestReport(
        nodeid=recovered.nodeid,
        location=recovered.location,
        keywords={},
        outcome="failed",
        longrepr="ConnectionError: example connection dropped",
        when=when,
    )
    output = StringIO()
    writer = TerminalWriter(output)
    reporter = SimpleNamespace(
        stats={"rerun": [failed_attempt]}, hasopt=lambda _: True, write_sep=writer.sep, _tw=writer
    )
    plugin.pytest_terminal_summary(cast(TerminalReporter, reporter))
    assert f"RERUN test_example.py::test_retry ({when})" in output.getvalue()
    assert "ConnectionError: example connection dropped" in output.getvalue()
