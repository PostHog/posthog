import dataclasses
from typing import Literal, Optional, get_args, TYPE_CHECKING


if TYPE_CHECKING:
    from posthog.models.plugin import PluginConfig
else:
    PluginConfig = None


SubTemplateId = Literal["early-access-feature-enrollment", "survey-response", "activity-log"]

SUB_TEMPLATE_ID: tuple[SubTemplateId, ...] = get_args(SubTemplateId)

HogFunctionTemplateType = Literal[
    "destination",
    "internal_destination",
    "site_destination",
    "site_app",
    "transformation",
    "shared",
    "email",
    "sms",
    "push",
    "broadcast",
    "activity",
    "alert",
]


@dataclasses.dataclass(frozen=True)
class HogFunctionSubTemplate:
    id: SubTemplateId
    name: str
    description: Optional[str] = None
    filters: Optional[dict] = None
    masking: Optional[dict] = None
    inputs_schema: Optional[list[dict]] = None
    type: Optional[HogFunctionTemplateType] = None


@dataclasses.dataclass(frozen=True)
class HogFunctionMapping:
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
    status: Literal["alpha", "beta", "stable", "free", "client-side"]
    type: HogFunctionTemplateType
    id: str
    name: str
    description: str
    hog: str
    inputs_schema: list[dict]
    category: list[str]
    sub_templates: Optional[list[HogFunctionSubTemplate]] = None
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


SUB_TEMPLATE_COMMON: dict[SubTemplateId, HogFunctionSubTemplate] = {
    "survey-response": HogFunctionSubTemplate(
        id="survey-response",
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
    "early-access-feature-enrollment": HogFunctionSubTemplate(
        id="early-access-feature-enrollment",
        name="Early Access Feature Enrollment",
        filters={"events": [{"id": "$feature_enrollment_update", "type": "events"}]},
    ),
    "activity-log": HogFunctionSubTemplate(
        id="activity-log",
        name="Team Activity",
        type="internal_destination",
        filters={"events": [{"id": "$activity_log_entry_created", "type": "events"}]},
    ),
}
