import dataclasses
from typing import Final, Literal, Optional, TypedDict

from posthog.temporal.common.errors import find_temporal_timeout_error, resolve_error_trace, unwrap_temporal_cause

from products.exports.backend.tasks.failure_handler import SLO_FAILURE_CATEGORY_QUERY, is_user_query_error_type

EXPORT_FAILURE_METADATA_KIND: Final[Literal["export_activity_failure"]] = "export_activity_failure"


class ExportFailureMetadata(TypedDict):
    kind: Literal["export_activity_failure"]
    slo_failure_details: dict[str, str | bool]


@dataclasses.dataclass
class ExportAssetActivityInputs:
    exported_asset_id: int
    source: Optional[str] = None


@dataclasses.dataclass
class ExportError:
    exception_class: str
    error_trace: str = ""
    failure_details: dict[str, str | bool] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ExportAssetResult:
    exported_asset_id: int
    success: bool
    error: Optional[ExportError] = None


def is_user_query_export_error(error: ExportError) -> bool:
    """Use activity metadata before falling back to legacy exception names."""

    failure_category = error.failure_details.get("failure_category")
    if failure_category is not None:
        return failure_category == SLO_FAILURE_CATEGORY_QUERY
    return is_user_query_error_type(error.exception_class)


def export_failure_metadata(slo_failure_details: dict[str, str | bool]) -> ExportFailureMetadata:
    """Wrap export failure fields in a named Temporal detail payload."""

    return {
        "kind": EXPORT_FAILURE_METADATA_KIND,
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
                "failure_category": "activity_timeout",
                "failure_component": "export_worker",
                "failure_retryable": True,
            },
        )
    if not cause.type:
        return None
    metadata = next(
        (
            detail
            for detail in reversed(cause.details)
            if isinstance(detail, dict) and detail.get("kind") == EXPORT_FAILURE_METADATA_KIND
        ),
        None,
    )
    failure_details = metadata.get("slo_failure_details", {}) if metadata else {}
    if not isinstance(failure_details, dict):
        failure_details = {}
    return ExportError(
        exception_class=cause.type,
        error_trace=resolve_error_trace(exc),
        failure_details=failure_details,
    )
