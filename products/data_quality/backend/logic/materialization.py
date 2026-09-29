from math import isfinite
from uuid import UUID

from ..facade.enums import CheckRunStatus, CheckSeverity, CheckType, SubjectType, SuiteRunStatus, SuiteRunTrigger
from ..models import DataQualityCheckRun, DataQualitySuiteRun

MAX_FAILURE_SUMMARIES = 3


def materialization_failure_summary(
    team_id: int,
    *,
    suite_run_id: str,
    data_modeling_job_id: str,
    saved_query_id: str,
    blocking_failures: int,
) -> str | None:
    if not isinstance(blocking_failures, int) or isinstance(blocking_failures, bool) or blocking_failures < 1:
        return None

    suite_id = _parse_uuid(suite_run_id)
    job_id = _parse_uuid(data_modeling_job_id)
    subject_id = _parse_uuid(saved_query_id)
    if suite_id is None or job_id is None or subject_id is None:
        return None

    suite_run = (
        DataQualitySuiteRun.objects.for_team(team_id)
        .filter(
            id=suite_id,
            trigger=SuiteRunTrigger.MATERIALIZATION,
            status=SuiteRunStatus.COMPLETED,
            data_modeling_job_id=job_id,
            subject_type=SubjectType.VIEW,
            subject_uuid=subject_id,
        )
        .only("id")
        .first()
    )
    if suite_run is None:
        return None

    snapshots = (
        DataQualityCheckRun.objects.for_team(team_id)
        .filter(
            suite_run_id=suite_run.id,
            subject_type=SubjectType.VIEW,
            subject_uuid=subject_id,
            status=CheckRunStatus.FAILED,
            check_severity=CheckSeverity.ERROR,
        )
        .order_by("created_at", "id")
    )
    if snapshots.count() != blocking_failures:
        return None

    details = [
        _failure_detail(snapshot.check_type, snapshot.check_config, snapshot.observed_value)
        for snapshot in snapshots[:MAX_FAILURE_SUMMARIES]
    ]
    if blocking_failures > MAX_FAILURE_SUMMARIES:
        details.append("additional checks also failed")
    return "; ".join(details)


def _parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError):
        return None


def _failure_detail(check_type: str, config: object, observed_value: object) -> str:
    if check_type == CheckType.ROW_COUNT:
        return _row_count_detail(config, observed_value)

    fixed_reasons = {
        CheckType.UNIQUE: "the uniqueness check found duplicate values",
        CheckType.NOT_NULL: "the not-null check found null values",
        CheckType.ACCEPTED_VALUES: "the accepted-values check found values outside its allowed set",
        CheckType.RELATIONSHIPS: "a data quality check failed",
        CheckType.FRESHNESS: "the latest timestamp is too old",
        CheckType.CUSTOM_SQL: "a data quality check failed",
    }
    return fixed_reasons.get(check_type, "a data quality check failed")


def _row_count_detail(config: object, observed_value: object) -> str:
    if not isinstance(config, dict):
        return "a data quality check failed"

    observed = _whole_number(observed_value)
    minimum = _whole_number(config.get("min"))
    maximum = _whole_number(config.get("max"))
    if (
        observed is None
        or (minimum is None and maximum is None)
        or (minimum is not None and maximum is not None and minimum > maximum)
    ):
        return "a data quality check failed"

    if minimum is not None and observed < minimum:
        return "the row count is below its minimum"
    if maximum is not None and observed > maximum:
        return "the row count is above its maximum"
    return "a data quality check failed"


def _whole_number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and isfinite(value) and value.is_integer() and value >= 0:
        return int(value)
    return None
