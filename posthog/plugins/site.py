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
    type: str


def get_site_config_from_schema(config_schema: Optional[list[dict]], config: Optional[dict]):
    if not config or not config_schema:
        return {}
    return {
        schema_element["key"]: config.get(schema_element["key"], schema_element.get("default", None))
        for schema_element in config_schema
        if schema_element.get("site", False) and schema_element.get("key", False)
    }


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

    return [asdict(WebJsUrl(source[0], site_app_url(source), "site_app")) for source in sources]


def get_decide_site_functions(team: "Team", using_database: str = "default") -> list[dict]:
    from posthog.models import HogFunction

    sources = (
        HogFunction.objects.db_manager(using_database)
        .filter(
            team=team,
            enabled=True,
            type__in=("site_destination", "site_app"),
            transpiled__isnull=False,
        )
        .values_list(
            "id",
            "updated_at",
            "type",
        )
        .all()
    )

    def site_function_url(source: tuple) -> str:
        hash = md5(str(source[1]).encode()).hexdigest()
        return f"/site_function/{source[0]}/{hash}/"

    return [
        asdict(WebJsUrl(source[0], site_function_url(source), source[2] or "site_destination")) for source in sources
    ]
