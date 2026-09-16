from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast
from xml.etree import ElementTree

import pytest

from _pytest._io import TerminalWriter
from _pytest.junitxml import LogXML
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


@pytest.mark.parametrize("final_outcome", ["passed", "failed", "skipped"])
@pytest.mark.parametrize("when", ["setup", "call", "teardown"])
@pytest.mark.parametrize("report_duration", ["call", "total"])
def test_retry_attempt_is_preserved_in_junit_xml(
    tmp_path: Path,
    final_outcome: Literal["passed", "failed", "skipped"],
    when: Literal["setup", "call", "teardown"],
    report_duration: Literal["call", "total"],
) -> None:
    junit_path = tmp_path / "junit.xml"
    xml = LogXML(junit_path, prefix=None, report_duration=report_duration)
    xml.pytest_sessionstart()
    plugin = _JUnitTimingsPlugin()
    session = cast(
        pytest.Session,
        SimpleNamespace(config=SimpleNamespace(pluginmanager=SimpleNamespace(list_name_plugin=lambda: [("xml", xml)]))),
    )
    plugin.pytest_sessionstart(session)

    first_attempt = pytest.TestReport(
        nodeid="test_example.py::test_retry",
        location=("test_example.py", 1, "test_retry"),
        keywords={},
        outcome=cast(Literal["passed", "failed", "skipped"], "rerun"),
        longrepr="first failure",
        when=when,
        duration=0.1,
    )
    if when == "teardown":
        first_call = pytest.TestReport(
            nodeid=first_attempt.nodeid,
            location=first_attempt.location,
            keywords={},
            outcome="passed",
            longrepr=None,
            when="call",
            duration=0.1,
        )
        plugin.pytest_runtest_logreport(first_call)
        xml.pytest_runtest_logreport(first_call)
    plugin.pytest_runtest_logreport(first_attempt)
    xml.pytest_runtest_logreport(first_attempt)

    final_call = pytest.TestReport(
        nodeid=first_attempt.nodeid,
        location=first_attempt.location,
        keywords={},
        outcome=final_outcome,
        longrepr=(
            "final failure"
            if final_outcome == "failed"
            else ("test_example.py", 1, "Skipped: final attempt skipped")
            if final_outcome == "skipped"
            else None
        ),
        when="call",
        duration=0.1,
    )
    plugin.pytest_runtest_logreport(final_call)
    xml.pytest_runtest_logreport(final_call)
    teardown = pytest.TestReport(
        nodeid=first_attempt.nodeid,
        location=first_attempt.location,
        keywords={},
        outcome="passed",
        longrepr=None,
        when="teardown",
        duration=0.01,
        rerun=1,
    )
    plugin.pytest_runtest_logreport(teardown)
    xml.pytest_runtest_logreport(teardown)
    plugin.pytest_sessionfinish(session, 0)
    xml.pytest_sessionfinish()

    suite = ElementTree.parse(junit_path).getroot().find("testsuite")
    assert suite is not None
    assert suite.get("tests") == "1"
    assert suite.get("failures") == ("1" if final_outcome == "failed" else "0")
    assert suite.get("skipped") == ("1" if final_outcome == "skipped" else "0")
    assert len(suite.findall("testcase")) == 1
    testcase = suite.find("testcase")
    assert testcase is not None
    if report_duration == "call":
        expected_time = 0.1 if when == "setup" else 0.2
    else:
        expected_time = 0.31 if when == "teardown" else 0.21
    assert float(testcase.get("time", "0")) == pytest.approx(expected_time)
    retry_tag = ("rerun" if final_outcome == "failed" else "flaky") + ("Failure" if when == "call" else "Error")
    retry = testcase.find(retry_tag)
    assert retry is not None
    assert retry.get("time") == ("0.100" if report_duration == "call" and when != "call" else None)
    assert retry.get("message") == "first failure"
    assert retry.findtext("stackTrace") == "first failure"
    assert (testcase.find("failure") is not None) == (final_outcome == "failed")
