import dataclasses
from typing import Literal, Optional


@dataclasses.dataclass(frozen=True)
class SiteFunctionTemplate:
    status: Literal["alpha", "beta", "stable", "free"]
    type: Literal["destination", "feature"]
    id: str
    name: str
    description: str
    source: str
    inputs_schema: list[dict]
    category: list[str]
    filters: Optional[dict] = None
    icon_url: Optional[str] = None
