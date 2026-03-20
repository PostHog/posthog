import dataclasses
from typing import Optional


@dataclasses.dataclass
class ExportAssetActivityInputs:
    exported_asset_id: int
    source: Optional[str] = None
    limit: Optional[int] = None
    max_height_pixels: Optional[int] = None


@dataclasses.dataclass
class ExportAssetResult:
    exported_asset_id: int
    success: bool
    exception_class: Optional[str] = None
    error_trace: Optional[str] = None
    insight_id: Optional[int] = None
    duration_ms: Optional[float] = None
    export_format: str = ""
    attempts: int = 1


@dataclasses.dataclass
class ExportError:
    exception_class: str
    error_trace: str = ""


@dataclasses.dataclass
class EmitDeliveryOutcomeInput:
    subscription_id: int
    team_id: int
    distinct_id: str
    outcome: str
    duration_ms: Optional[float] = None
    assets_with_content: int = 0
    total_assets: int = 0
    errors: list[ExportError] = dataclasses.field(default_factory=list)
