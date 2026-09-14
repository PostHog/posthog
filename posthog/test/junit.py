import pytest


def set_junit_report_location(item: pytest.Item, report: pytest.TestReport) -> None:
    test_file = item.path.relative_to(item.config.rootpath).as_posix()
    report.location = (test_file, report.location[1], report.location[2])
