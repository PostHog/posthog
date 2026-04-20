"""JUnit XML and Playwright JSON parsers for ci_monitoring."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

import structlog

from .facade.enums import TestExecutionStatus

logger = structlog.get_logger(__name__)


@dataclass
class ParsedTestResult:
    identifier: str
    classname: str
    name: str
    status: TestExecutionStatus
    duration_ms: int | None
    error_message: str | None
    retry_count: int
    file_path: str | None


def parse_junit_xml(xml_content: str | bytes) -> list[ParsedTestResult]:
    """
    Parse a JUnit XML file into test results.

    Handles pytest (with pytest-rerunfailures) and standard JUnit formats.
    Flaky detection: a testcase with <rerun> children that eventually passed
    is marked as FLAKY.
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        logger.warning("ci_monitoring.malformed_junit_xml")
        return []

    results: list[ParsedTestResult] = []

    testcases = root.findall(".//testcase")
    if not testcases:
        return results

    for tc in testcases:
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        time_attr = tc.get("time")
        file_path = tc.get("file")

        duration_ms = int(float(time_attr) * 1000) if time_attr else None
        identifier = f"{classname}.{name}" if classname else name

        if not identifier:
            continue

        # Detect status from child elements
        failures = tc.findall("failure")
        errors = tc.findall("error")
        skipped = tc.findall("skipped")
        reruns = tc.findall("rerun")

        error_message: str | None = None
        retry_count = len(reruns)

        if skipped:
            status = TestExecutionStatus.SKIPPED
        elif reruns and not failures and not errors:
            # Had reruns but final result was pass -> flaky
            status = TestExecutionStatus.FLAKY
            error_message = _extract_rerun_message(reruns)
        elif failures or errors:
            status = TestExecutionStatus.FAILED
            error_message = _extract_failure_message(failures or errors)
        else:
            status = TestExecutionStatus.PASSED

        results.append(
            ParsedTestResult(
                identifier=identifier,
                classname=classname,
                name=name,
                status=status,
                duration_ms=duration_ms,
                error_message=_truncate(error_message, 2000),
                retry_count=retry_count,
                file_path=file_path,
            )
        )

    return results


def _extract_failure_message(elements: list[ET.Element]) -> str | None:
    for el in elements:
        msg = el.get("message") or el.text
        if msg:
            return msg.strip()
    return None


def _extract_rerun_message(reruns: list[ET.Element]) -> str | None:
    for rerun in reruns:
        msg = rerun.get("message") or rerun.text
        if msg:
            return msg.strip()
    return None


def _truncate(s: str | None, max_len: int) -> str | None:
    if s is None:
        return None
    return s[:max_len] if len(s) > max_len else s
