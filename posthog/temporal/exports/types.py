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
    # Raw `str(e)` from the underlying exception. Carried alongside `exception_class`
    # so callers can rebuild the canonical "<type>: <message>" rendering even when
    # the failure was returned from an activity instead of raised as an
    # ApplicationError (whose own `__str__` produces that format).
    error_message: str = ""


@dataclasses.dataclass
class ExportAssetResult:
    exported_asset_id: int
    success: bool
    error: Optional[ExportError] = None


def extract_error_details(exc: BaseException) -> ExportError | None:
    cause = unwrap_temporal_cause(exc)
    if cause is None or not cause.type:
        return None
    return ExportError(
        exception_class=cause.type,
        error_trace=resolve_error_trace(exc),
        error_message=getattr(cause, "message", "") or "",
    )
