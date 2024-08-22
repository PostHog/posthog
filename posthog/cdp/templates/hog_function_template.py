import dataclasses
from typing import Literal, Optional


@dataclasses.dataclass(frozen=True)
class HogFunctionTemplate:
    status: Literal["alpha", "beta", "stable", "free"]
    id: str
    name: str
    description: str
    hog: str
    inputs_schema: list[dict]
    filters: Optional[dict] = None
    icon_url: Optional[str] = None
