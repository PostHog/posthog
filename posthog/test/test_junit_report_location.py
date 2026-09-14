from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

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
