import dataclasses
from typing import Literal, Optional, get_args, TYPE_CHECKING


if TYPE_CHECKING:
    from posthog.models.plugin import PluginConfig
else:
    PluginConfig = None


SubTemplateId = Literal["early_access_feature_enrollment", "survey_response"]

SUB_TEMPLATE_ID: tuple[SubTemplateId, ...] = get_args(SubTemplateId)


@dataclasses.dataclass(frozen=True)
class HogFunctionSubTemplate:
    id: SubTemplateId
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


class HogFunctionTemplateMigrator:
    plugin_url: str

    @classmethod
    def migrate(cls, obj: PluginConfig) -> dict:
        # Return a dict for the template of a new HogFunction
        raise NotImplementedError()
