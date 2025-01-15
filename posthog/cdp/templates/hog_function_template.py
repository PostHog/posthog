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
    input_schema_overrides: Optional[dict[str, dict]] = None
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


def derive_sub_templates(templates: list[HogFunctionTemplate]) -> list[HogFunctionTemplate]:
    sub_templates = []
    for template in templates:
        for sub_template in template.sub_templates or []:
            merged_id = f"{template.id}-{sub_template.id}"
            template_params = dataclasses.asdict(template)
            sub_template_params = dataclasses.asdict(sub_template)

            # Override inputs_schema if set
            input_schema_overrides = sub_template_params.pop("input_schema_overrides")
            if input_schema_overrides:
                new_input_schema = []
                for schema in template_params["inputs_schema"]:
                    if schema["key"] in input_schema_overrides:
                        schema.update(input_schema_overrides[schema["key"]])
                    new_input_schema.append(schema)
                template_params["inputs_schema"] = new_input_schema

            # Get rid of the sub_templates from the template
            template_params.pop("sub_templates")
            # Update with the sub template params if not none
            for key, value in sub_template_params.items():
                if value is not None:
                    template_params[key] = value

            template_params["id"] = merged_id
            merged_template = HogFunctionTemplate(**template_params)
            sub_templates.append(merged_template)

    return sub_templates


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
