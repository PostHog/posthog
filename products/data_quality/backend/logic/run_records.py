"""Write one check execution down.

The columns a run records are what every history gate later judges it by, so the field list is
spelled out here rather than forwarded as ``**kwargs``: a caller that omits the declared subject or
misspells ``referenced_subjects`` would strand its own history behind a fail-closed gate.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from ..facade.enums import CheckRunStatus, CheckSeverity
from ..models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun


def record_check_run(
    team_id: int,
    *,
    suite_run: DataQualitySuiteRun,
    subject_type: str,
    subject_uuid: str | UUID,
    subject_name: str,
    check_type: str,
    check_fingerprint: str,
    status: CheckRunStatus | str,
    quality_check: DataQualityCheck | None = None,
    column_name: str = "",
    check_config: dict[str, Any] | None = None,
    check_severity: CheckSeverity | str | None = None,
    referenced_subjects: list[dict[str, str]] | None = None,
    failed_row_count: int | None = None,
    observed_value: float | None = None,
    compiled_query: str = "",
    error: str = "",
    duration_ms: int | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> DataQualityCheckRun:
    """Record one check execution."""
    return DataQualityCheckRun.objects.for_team(team_id).create(
        team_id=team_id,
        suite_run=suite_run,
        subject_type=subject_type,
        subject_uuid=subject_uuid,
        subject_name=subject_name,
        check_type=check_type,
        check_fingerprint=check_fingerprint,
        status=status,
        quality_check=quality_check,
        column_name=column_name,
        check_config=check_config,
        check_severity=check_severity,
        referenced_subjects=referenced_subjects,
        failed_row_count=failed_row_count,
        observed_value=observed_value,
        compiled_query=compiled_query,
        error=error,
        duration_ms=duration_ms,
        started_at=started_at,
        finished_at=finished_at,
    )
