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


@pytest.mark.parametrize("when", ["setup", "call", "teardown"])
def test_retry_failure_uses_separate_junit_file(tmp_path: Path, when: Literal["setup", "call", "teardown"]) -> None:
    junit_path = tmp_path / "junit.xml"
    xml = LogXML(junit_path, prefix=None, report_duration="call")
    xml.pytest_sessionstart()
    plugin = _JUnitTimingsPlugin()
    session = cast(
        pytest.Session,
        SimpleNamespace(config=SimpleNamespace(pluginmanager=SimpleNamespace(list_name_plugin=lambda: [("xml", xml)]))),
    )
    plugin.pytest_sessionstart(session)

    retry = pytest.TestReport(
        nodeid="test_example.py::test_retry",
        location=("test_example.py", 1, "test_retry"),
        keywords={},
        outcome=cast(Literal["passed", "failed", "skipped"], "rerun"),
        longrepr="first failure",
        when=when,
        duration=0.1,
        rerun=0,
    )
    plugin.pytest_runtest_logreport(retry)
    xml.pytest_runtest_logreport(retry)

    final_call = pytest.TestReport(
        nodeid=retry.nodeid,
        location=retry.location,
        keywords={},
        outcome="skipped",
        longrepr=("test_example.py", 1, "Skipped: final attempt skipped"),
        when="call",
        duration=0.1,
    )
    plugin.pytest_runtest_logreport(final_call)
    xml.pytest_runtest_logreport(final_call)
    teardown = pytest.TestReport(
        nodeid=retry.nodeid,
        location=retry.location,
        keywords={},
        outcome="passed",
        longrepr=None,
        when="teardown",
        rerun=1,
    )
    plugin.pytest_runtest_logreport(teardown)
    xml.pytest_runtest_logreport(teardown)
    plugin.pytest_sessionfinish(session, 0)
    xml.pytest_sessionfinish()

    main_suite = ElementTree.parse(junit_path).getroot().find("testsuite")
    assert main_suite is not None
    assert main_suite.find(".//skipped") is not None
    assert main_suite.find(".//failure") is None
    assert main_suite.find(".//error") is None

    retry_suite = ElementTree.parse(tmp_path / "junit-retry-failures.xml").getroot().find("testsuite")
    assert retry_suite is not None
    assert retry_suite.get("tests") == "1"
    assert retry_suite.get("failures") == ("1" if when == "call" else "0")
    assert retry_suite.get("errors") == ("0" if when == "call" else "1")
    testcase = retry_suite.find("testcase")
    assert testcase is not None
    assert testcase.get("classname") == "test_example"
    assert testcase.get("name") == "test_retry"
    assert testcase.get("file") == "test_example.py"
    assert testcase.get("attempt_number") == "1"
    failure = testcase.find("failure" if when == "call" else "error")
    assert failure is not None
    assert failure.get("message") == "first failure"


def test_retry_junit_removes_stale_file_without_reruns(tmp_path: Path) -> None:
    junit_path = tmp_path / "junit.xml"
    retry_path = tmp_path / "junit-retry-failures.xml"
    retry_path.write_text("stale")
    xml = LogXML(junit_path, prefix=None)
    xml.pytest_sessionstart()
    plugin = _JUnitTimingsPlugin()
    session = cast(
        pytest.Session,
        SimpleNamespace(config=SimpleNamespace(pluginmanager=SimpleNamespace(list_name_plugin=lambda: [("xml", xml)]))),
    )
    plugin.pytest_sessionstart(session)
    plugin.pytest_sessionfinish(session, 0)

    assert not retry_path.exists()
