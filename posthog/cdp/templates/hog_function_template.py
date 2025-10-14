import dataclasses
from typing import TYPE_CHECKING, Literal

from posthog.api.hog_function_template import HogFunctionTemplateSerializer
from posthog.models.hog_function_template import HogFunctionTemplate

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
    name: str | None = None
    filters: dict | None = None
    inputs: dict | None = None
    inputs_schema: list[dict] | None = None


@dataclasses.dataclass(frozen=True)
class HogFunctionMappingTemplate:
    name: str
    include_by_default: bool | None = None
    filters: dict | None = None
    inputs: dict | None = None
    inputs_schema: list[dict] | None = None


@dataclasses.dataclass(frozen=True)
class HogFunctionTemplateDC:
    status: Literal["alpha", "beta", "stable", "deprecated", "coming_soon", "hidden"]
    free: bool
    type: HogFunctionTemplateType
    id: str
    name: str
    code: str
    code_language: Literal["javascript", "hog"]
    inputs_schema: list[dict]
    category: list[str]
    description: str | None = None
    filters: dict | None = None
    mapping_templates: list[HogFunctionMappingTemplate] | None = None
    masking: dict | None = None
    icon_url: str | None = None


class HogFunctionTemplateMigrator:
    plugin_url: str

    @classmethod
    def migrate(cls, obj: PluginConfig) -> dict:
        # Return a dict for the template of a new HogFunction
        raise NotImplementedError()


def sync_template_to_db(template_data: dict | HogFunctionTemplateDC) -> HogFunctionTemplate:
    if isinstance(template_data, HogFunctionTemplateDC):
        template_data = dataclasses.asdict(template_data)

    template = HogFunctionTemplate.get_template(template_data["id"])
    if template:
        serializer = HogFunctionTemplateSerializer(template, data=template_data)
    else:
        serializer = HogFunctionTemplateSerializer(data=template_data)

    serializer.is_valid(raise_exception=True)
    return serializer.save()
