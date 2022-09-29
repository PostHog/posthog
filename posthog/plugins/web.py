from dataclasses import dataclass
from typing import List, Optional


@dataclass
class WebSource:
    id: int
    source: str
    token: str
    config_schema: List[dict]
    config: dict


def get_transpiled_web_source(id: int, token: str) -> Optional[WebSource]:
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

    return WebSource(*(list(response)))  # type: ignore


def get_transpiled_web_sources(team) -> List[WebSource]:
    """
    :type team: posthog.models.Team
    """
    from posthog.models import PluginConfig, PluginSourceFile

    sources = (
        PluginConfig.objects.filter(
            team=team,
            enabled=True,
            plugin__pluginsourcefile__filename="web.ts",
            plugin__pluginsourcefile__status=PluginSourceFile.Status.TRANSPILED,
        )
        .values_list("id", "plugin__pluginsourcefile__transpiled", "web_token", "plugin__config_schema", "config")
        .all()
    )
    return [WebSource(*(list(source))) for source in sources]  # type: ignore
