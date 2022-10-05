from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from posthog.models import Team


@dataclass
class WebJsSource:
    id: int
    source: str
    token: str
    config_schema: List[dict]
    config: dict


@dataclass
class WebJsUrl:
    id: int
    url: str


def get_transpiled_web_source(id: int, token: str) -> Optional[WebJsSource]:
    from posthog.models import PluginConfig, PluginSourceFile

    response = (
        PluginConfig.objects.filter(
            id=id,
            web_token=token,
            enabled=True,
            plugin__pluginsourcefile__filename="web.ts",
            plugin__pluginsourcefile__status=PluginSourceFile.Status.TRANSPILED,
        )
        .values_list("id", "plugin__pluginsourcefile__transpiled", "web_token", "plugin__config_schema", "config")
        .first()
    )

    if not response:
        return None

    return WebJsSource(*(list(response)))  # type: ignore


def get_decide_web_js_inject(team: "Team") -> List[dict]:
    from posthog.models import PluginConfig, PluginSourceFile

    sources = (
        PluginConfig.objects.filter(
            team=team,
            enabled=True,
            plugin__pluginsourcefile__filename="web.ts",
            plugin__pluginsourcefile__status=PluginSourceFile.Status.TRANSPILED,
        )
        .values_list("id", "web_token")
        .all()
    )
    return [asdict(WebJsUrl(source[0], f"/web_js/{source[0]}/{source[1]}/")) for source in sources]


def get_web_config_from_schema(config_schema: Optional[List[dict]], config: Optional[dict]):
    if not config or not config_schema:
        return {}
    return {
        schema_element["key"]: config.get(schema_element["key"], schema_element.get("default", None))
        for schema_element in config_schema
        if schema_element.get("web", False) and schema_element.get("key", False)
    }
