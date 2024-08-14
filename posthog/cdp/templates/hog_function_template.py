import dataclasses
from typing import Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.models.plugin import PluginConfig
else:
    PluginConfig = None


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


class HogFunctionTemplateMigrator:
    plugin_url: str

    @classmethod
    def migrate(cls, obj: PluginConfig) -> dict:
        # Return a dict for the template of a new HogFunction
        raise NotImplementedError()
