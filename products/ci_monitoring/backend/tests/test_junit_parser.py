from products.ci_monitoring.backend.facade.enums import TestExecutionStatus
from products.ci_monitoring.backend.junit_parser import parse_junit_xml

JUNIT_PASSING = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="2" errors="0" failures="0">
    <testcase classname="tests.test_math" name="test_add" time="0.001" file="tests/test_math.py"/>
    <testcase classname="tests.test_math" name="test_subtract" time="0.002" file="tests/test_math.py"/>
</testsuite>
"""

JUNIT_MIXED = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="4" errors="1" failures="1" skipped="1">
    <testcase classname="tests.test_api" name="test_ok" time="0.5"/>
    <testcase classname="tests.test_api" name="test_fail" time="1.2">
        <failure message="AssertionError: expected 200 got 500">Traceback...</failure>
    </testcase>
    <testcase classname="tests.test_api" name="test_error" time="0.0">
        <error message="ConnectionError">Traceback...</error>
    </testcase>
    <testcase classname="tests.test_api" name="test_skip" time="0.0">
        <skipped message="not implemented"/>
    </testcase>
</testsuite>
"""

JUNIT_FLAKY = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1">
    <testcase classname="tests.test_flaky" name="test_timing" time="2.0" file="tests/test_flaky.py">
        <rerun message="TimeoutError">first attempt failed</rerun>
        <rerun message="TimeoutError">second attempt failed</rerun>
    </testcase>
</testsuite>
"""

JUNIT_NESTED = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
    <testsuite name="suite1" tests="1">
        <testcase classname="a.b" name="test_one" time="0.1"/>
    </testsuite>
    <testsuite name="suite2" tests="1">
        <testcase classname="c.d" name="test_two" time="0.2"/>
    </testsuite>
</testsuites>
"""


class TestParseJunitXml:
    def test_all_passing(self):
        results = parse_junit_xml(JUNIT_PASSING)
        assert len(results) == 2
        assert all(r.status == TestExecutionStatus.PASSED for r in results)
        assert results[0].identifier == "tests.test_math.test_add"
        assert results[0].duration_ms == 1
        assert results[0].file_path == "tests/test_math.py"

    def test_mixed_statuses(self):
        results = parse_junit_xml(JUNIT_MIXED)
        assert len(results) == 4

        by_name = {r.name: r for r in results}
        assert by_name["test_ok"].status == TestExecutionStatus.PASSED
        assert by_name["test_fail"].status == TestExecutionStatus.FAILED
        assert by_name["test_fail"].error_message == "AssertionError: expected 200 got 500"
        assert by_name["test_error"].status == TestExecutionStatus.FAILED
        assert by_name["test_skip"].status == TestExecutionStatus.SKIPPED

    def test_flaky_with_reruns(self):
        results = parse_junit_xml(JUNIT_FLAKY)
        assert len(results) == 1
        r = results[0]
        assert r.status == TestExecutionStatus.FLAKY
        assert r.retry_count == 2
        assert r.error_message == "TimeoutError"
        assert r.file_path == "tests/test_flaky.py"

    def test_nested_testsuites(self):
        results = parse_junit_xml(JUNIT_NESTED)
        assert len(results) == 2
        assert results[0].identifier == "a.b.test_one"
        assert results[1].identifier == "c.d.test_two"

    def test_empty_xml(self):
        results = parse_junit_xml("<testsuite/>")
        assert results == []
