import dataclasses
from typing import Literal, Optional, TypedDict

from posthog.temporal.common.errors import resolve_error_trace, unwrap_temporal_cause

EXPORT_FAILURE_METADATA_KIND = "export_activity_failure"


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


def export_failure_metadata(slo_failure_details: dict[str, str | bool]) -> ExportFailureMetadata:
    """Wrap export failure fields in a named Temporal detail payload."""

    return {
        "kind": EXPORT_FAILURE_METADATA_KIND,
        "slo_failure_details": slo_failure_details,
    }


def extract_error_details(exc: BaseException) -> ExportError | None:
    cause = unwrap_temporal_cause(exc)
    if cause is None or not cause.type:
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
