from dataclasses import asdict, dataclass
from hashlib import md5
import json
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


@dataclass
class WebJsApp:
    id: int
    source: str
    token: str
    config_schema: list[dict]
    config: dict


def get_site_config_from_schema(config_schema: Optional[list[dict]], config: Optional[dict]):
    if not config or not config_schema:
        return {}
    return {
        schema_element["key"]: config.get(schema_element["key"], schema_element.get("default", None))
        for schema_element in config_schema
        if schema_element.get("site", False) and schema_element.get("key", False)
    }


def _get_transpiled_site_source(id: int, token: str) -> Optional[WebJsSource]:
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

    print(response)

    if not response:
        return None

    return WebJsSource(*(list(response)))


def get_site_apps_for_team(team_id: int) -> list[WebJsSource]:
    from posthog.models import PluginConfig, PluginSourceFile

    rows = (
        PluginConfig.objects.filter(
            team_id=team_id,
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
        .all()
    )

    items = []

    for row in rows:
        items.append(WebJsSource(*(list(row))))

    return items


def _generate_site_app_script(source_file: WebJsSource) -> str:
    id = source_file.id
    source = source_file.source
    config = get_site_config_from_schema(source_file.config_schema, source_file.config)
    return f"{source}().inject({{config:{json.dumps(config)},posthog:window['__$$ph_site_app_{id}']}})"


def get_site_app_script(id: int, token: str) -> str:
    source_file = _get_transpiled_site_source(id, token) if token else None
    if not source_file:
        raise Exception("No source file found")

    return _generate_site_app_script(source_file)


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
