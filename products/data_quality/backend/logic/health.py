"""Roll a subject's checks up into one health verdict.

Pure, and deliberately the only implementation: the REST endpoint and the
``information_schema.data_quality_health`` table must never disagree about what "failing" means.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from ..facade.enums import CheckRunStatus, CheckSeverity, SubjectHealth


@dataclass(frozen=True)
class CheckStatusRow:
    """The denormalized last-run state of one check, which is all a rollup needs."""

    severity: str
    last_status: str


def roll_up_health(rows: Iterable[CheckStatusRow]) -> SubjectHealth:
    """Worst-first: an error-severity failure outranks an execution error, which outranks a warning."""
    statuses = list(rows)
    if not statuses:
        return SubjectHealth.UNKNOWN

    if any(_is_error_failure(row) for row in statuses):
        return SubjectHealth.FAILING
    if any(row.last_status == CheckRunStatus.ERRORED for row in statuses):
        return SubjectHealth.ERRORING
    if any(row.last_status == CheckRunStatus.FAILED for row in statuses):
        return SubjectHealth.WARN
    if any(row.last_status == CheckRunStatus.PASSED for row in statuses):
        return SubjectHealth.HEALTHY
    return SubjectHealth.UNKNOWN


def _is_error_failure(row: CheckStatusRow) -> bool:
    return row.last_status == CheckRunStatus.FAILED and row.severity == CheckSeverity.ERROR
