import dataclasses
from typing import Literal, Optional


@dataclasses.dataclass(frozen=True)
class HogFunctionSubTemplate:
    id: str
    name: str
    description: Optional[str] = None
    filters: Optional[dict] = None
    masking: Optional[dict] = None
    inputs: Optional[dict] = None


@dataclasses.dataclass(frozen=True)
class HogFunctionTemplate:
    status: Literal["alpha", "beta", "stable", "free"]
    id: str
    name: str
    description: str
    hog: str
    inputs_schema: list[dict]
    sub_templates: Optional[list[HogFunctionSubTemplate]] = None
    filters: Optional[dict] = None
    masking: Optional[dict] = None
    icon_url: Optional[str] = None
