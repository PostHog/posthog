import dataclasses
from typing import Optional, TypedDict, cast

from posthog.dataclasses import frozen
from posthog.temporal.common.errors import find_temporal_timeout_error, resolve_error_trace, unwrap_temporal_cause

from products.exports.backend.tasks.failure_handler import (
    SLO_FAILURE_CATEGORY_ACTIVITY_TIMEOUT,
    SLO_FAILURE_CATEGORY_QUERY,
    SLO_FAILURE_COMPONENT_EXPORT_WORKER,
    ExportFailureDetails,
    is_user_query_error_type,
)

_EXPORT_FAILURE_METADATA_KIND = "export_activity_failure"


class ExportFailureMetadata(TypedDict):
    kind: str
    slo_failure_details: ExportFailureDetails


@dataclasses.dataclass
class ExportAssetActivityInputs:
    exported_asset_id: int
    source: Optional[str] = None


@frozen
class ExportError:
    exception_class: str
    error_trace: str = ""
    failure_details: ExportFailureDetails | None = None


@dataclasses.dataclass
class ExportAssetResult:
    exported_asset_id: int
    success: bool
    error: Optional[ExportError] = None


def is_user_query_export_error(error: ExportError) -> bool:
    if error.failure_details is not None:
        return error.failure_details["failure_category"] == SLO_FAILURE_CATEGORY_QUERY
    return is_user_query_error_type(error.exception_class)


def export_failure_metadata(slo_failure_details: ExportFailureDetails) -> ExportFailureMetadata:
    return {
        "kind": _EXPORT_FAILURE_METADATA_KIND,
        "slo_failure_details": slo_failure_details,
    }


def extract_error_details(exc: BaseException) -> ExportError | None:
    cause = unwrap_temporal_cause(exc)
    if cause is None:
        timeout = find_temporal_timeout_error(exc)
        if timeout is None:
            return None
        return ExportError(
            exception_class=type(timeout).__name__,
            error_trace=resolve_error_trace(exc),
            failure_details={
                "failure_category": SLO_FAILURE_CATEGORY_ACTIVITY_TIMEOUT,
                "failure_component": SLO_FAILURE_COMPONENT_EXPORT_WORKER,
                "failure_retryable": True,
            },
        )
    if not cause.type:
        return None
    metadata = next(
        (
            detail
            for detail in reversed(cause.details)
            if isinstance(detail, dict) and detail.get("kind") == _EXPORT_FAILURE_METADATA_KIND
        ),
        None,
    )
    raw_failure_details: object = metadata.get("slo_failure_details") if metadata else None
    failure_details = cast(ExportFailureDetails, raw_failure_details) if isinstance(raw_failure_details, dict) else None
    return ExportError(
        exception_class=cause.type,
        error_trace=resolve_error_trace(exc),
        failure_details=failure_details,
    )
