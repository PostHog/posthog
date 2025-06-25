import dataclasses
from typing import Literal, Optional, TYPE_CHECKING


if TYPE_CHECKING:
    from posthog.models.plugin import PluginConfig
else:
    PluginConfig = None


SubTemplateId = Literal[
    "activity-log",
    "error-tracking-issue-created",
    "error-tracking-issue-reopened",
    "insight-alert-firing",
]


# Keep in sync with HogFunctionType
HogFunctionTemplateType = Literal[
    "destination",
    "site_destination",
    "internal_destination",
    "source_webhook",
    "site_app",
    "transformation",
]


@dataclasses.dataclass(frozen=True)
class HogFunctionMapping:
    name: Optional[str] = None
    filters: Optional[dict] = None
    inputs: Optional[dict] = None
    inputs_schema: Optional[list[dict]] = None


@dataclasses.dataclass(frozen=True)
class HogFunctionMappingTemplate:
    name: str
    include_by_default: Optional[bool] = None
    filters: Optional[dict] = None
    inputs: Optional[dict] = None
    inputs_schema: Optional[list[dict]] = None


@dataclasses.dataclass(frozen=True)
class HogFunctionTemplate:
    status: Literal["alpha", "beta", "stable", "deprecated", "coming_soon", "hidden"]
    free: bool
    type: HogFunctionTemplateType
    id: str
    name: str
    hog: str
    inputs_schema: list[dict]
    category: list[str]
    description: Optional[str] = None
    filters: Optional[dict] = None
    mappings: Optional[list[HogFunctionMapping]] = None
    mapping_templates: Optional[list[HogFunctionMappingTemplate]] = None
    masking: Optional[dict] = None
    icon_url: Optional[str] = None


class HogFunctionTemplateMigrator:
    plugin_url: str

    @classmethod
    def migrate(cls, obj: PluginConfig) -> dict:
        # Return a dict for the template of a new HogFunction
        raise NotImplementedError()
