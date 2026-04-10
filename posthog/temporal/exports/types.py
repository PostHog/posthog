import typing
import dataclasses
from typing import Optional

from temporalio.exceptions import ActivityError, ApplicationError


class ExportErrorDetails(typing.NamedTuple):
    exception_class: str | None = None
    error_trace: str | None = None


def extract_error_details(exc: BaseException) -> ExportErrorDetails:
    """Extract failure metadata from a Temporal activity exception chain.

    asyncio.gather(return_exceptions=True) yields BaseException, but Temporal
    wraps activity failures as ActivityError -> ApplicationError. We narrow
    through that chain to reach the structured details.
    """
    if not isinstance(exc, ActivityError) or not isinstance(exc.cause, ApplicationError):
        return ExportErrorDetails()

    cause = exc.cause
    return ExportErrorDetails(
        exception_class=cause.type,
        error_trace=cause.details[0] if len(cause.details) >= 1 and isinstance(cause.details[0], str) else None,
    )


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
