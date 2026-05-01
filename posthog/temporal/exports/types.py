import dataclasses
from typing import Optional

from posthog.temporal.common.errors import resolve_error_trace, unwrap_temporal_cause


@dataclasses.dataclass
class ExportAssetActivityInputs:
    exported_asset_id: int
    source: Optional[str] = None


@dataclasses.dataclass
class ExportError:
    exception_class: str
    error_trace: str = ""


@dataclasses.dataclass
class ExportAssetResult:
    exported_asset_id: int
    success: bool
    error: Optional[ExportError] = None


def extract_error_details(exc: BaseException) -> ExportError | None:
    cause = unwrap_temporal_cause(exc)
    if cause is None or not cause.type:
        return None
    return ExportError(exception_class=cause.type, error_trace=resolve_error_trace(exc))
