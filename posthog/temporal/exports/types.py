import typing
import dataclasses
from typing import Optional

from temporalio.exceptions import ActivityError, ApplicationError

from posthog.slo.types import SloOutcome


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

    details = exc.cause.details
    return ExportErrorDetails(
        exception_class=details[0] if len(details) >= 1 and isinstance(details[0], str) else None,
        error_trace=details[1] if len(details) >= 2 and isinstance(details[1], str) else None,
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


@dataclasses.dataclass
class EmitDeliveryOutcomeInput:
    subscription_id: int
    team_id: int
    distinct_id: str
    outcome: SloOutcome
    duration_ms: Optional[float] = None
    assets_with_content: int = 0
    total_assets: int = 0
    errors: list[ExportError] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class EmitExportOutcomeInput:
    exported_asset_id: int
    team_id: int
    distinct_id: str
    outcome: SloOutcome
    duration_ms: Optional[float] = None
    export_format: str = ""
    error: Optional[ExportError] = None
