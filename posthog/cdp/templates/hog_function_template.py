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
    category: list[str]
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


SUB_TEMPLATE_COMMON: dict[SubTemplateId, HogFunctionSubTemplate] = {
    "survey_response": HogFunctionSubTemplate(
        id="survey_response",
        name="Survey Response",
        filters={
            "events": [
                {
                    "id": "survey sent",
                    "type": "events",
                    "properties": [
                        {
                            "key": "$survey_response",
                            "type": "event",
                            "value": "is_set",
                            "operator": "is_set",
                        },
                    ],
                }
            ]
        },
    ),
    "early_access_feature_enrollment": HogFunctionSubTemplate(
        id="early_access_feature_enrollment",
        name="Early Access Feature Enrollment",
        filters={"events": [{"id": "$feature_enrollment_update", "type": "events"}]},
    ),
}
