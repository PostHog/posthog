from dataclasses import asdict, dataclass
from hashlib import md5
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from posthog.models import Team


@dataclass
class WebJsSource:
    id: int
    source: str
    token: str
    config_schema: list[dict]
    config: dict


@dataclass
class WebJsUrl:
    id: int
    url: str


def get_transpiled_site_source(id: int, token: str) -> Optional[WebJsSource]:
    from posthog.models import PluginConfig, PluginSourceFile

    response = (
        PluginConfig.objects.filter(
            id=id,
            web_token=token,
            enabled=True,
            plugin__pluginsourcefile__filename="site.ts",
            plugin__pluginsourcefile__status=PluginSourceFile.Status.TRANSPILED,
        )
        .values_list(
            "id",
            "plugin__pluginsourcefile__transpiled",
            "web_token",
            "plugin__config_schema",
            "config",
        )
        .first()
    )

    if not response:
        return None

    return WebJsSource(*(list(response)))


def get_decide_site_apps(team: "Team", using_database: str = "default") -> list[dict]:
    from posthog.models import PluginConfig, PluginSourceFile

    sources = (
        PluginConfig.objects.db_manager(using_database)
        .filter(
            team=team,
            enabled=True,
            plugin__pluginsourcefile__filename="site.ts",
            plugin__pluginsourcefile__status=PluginSourceFile.Status.TRANSPILED,
        )
        .values_list(
            "id",
            "web_token",
            "plugin__pluginsourcefile__updated_at",
            "plugin__updated_at",
            "updated_at",
        )
        .all()
    )

    def site_app_url(source: tuple) -> str:
        hash = md5(f"{source[2]}-{source[3]}-{source[4]}".encode()).hexdigest()
        return f"/site_app/{source[0]}/{source[1]}/{hash}/"

    return [asdict(WebJsUrl(source[0], site_app_url(source))) for source in sources]


def get_site_config_from_schema(config_schema: Optional[list[dict]], config: Optional[dict]):
    if not config or not config_schema:
        return {}
    return {
        schema_element["key"]: config.get(schema_element["key"], schema_element.get("default", None))
        for schema_element in config_schema
        if schema_element.get("site", False) and schema_element.get("key", False)
    }
