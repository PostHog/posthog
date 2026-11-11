import json

from django.http import HttpRequest
from django.urls import reverse

from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.admin.console.tools import ConsoleTool, Notice, Output, Page
from posthog.models.remote_config import RemoteConfig
from posthog.models.team.team import Team


def _cached_config(team: Team) -> Page:
    hypercache = RemoteConfig.get_hypercache()
    cache_key = hypercache.get_cache_key(team.api_token)
    team_url = reverse("admin_console_team", kwargs={"pk": team.pk})
    heading = Notice(
        text=f"Team '{team.name}' ({team.pk}). Cache key: {cache_key}", link_text="Back to the team", href=team_url
    )
    cached_data, source = hypercache.peek_from_cache_with_source(team.api_token)
    if source is None:
        return Page(blocks=(heading, Notice(text="Nothing is cached for this team. Rebuild the cache to fill it.")))
    if cached_data is None:
        return Page(blocks=(heading, Notice(text=f"The cache in {source} says that this team does not exist.")))
    return Page(
        blocks=(
            heading,
            Notice(text=f"Read from {source}."),
            Output(text=json.dumps(cached_data, indent=2, default=str)),
        )
    )


@console.register_tool
class RemoteConfigCacheTool(ConsoleTool):
    key = "remote-config-cache"
    title = "Remote config cache"
    owner = DEV_EXPERIENCE
    group = "Data"
    description = "The config JSON that SDKs read for one team, as the cache holds it."

    def page(self, request: HttpRequest) -> Page:
        team_id = request.GET.get("team", "").strip()
        team = Team.objects.filter(pk=int(team_id)).first() if team_id.isascii() and team_id.isdigit() else None
        if team is None:
            return Page(
                blocks=(
                    Notice(
                        text="Open this page from the Remote config cache panel on a team page.",
                        link_text="Find a team",
                        href="/admin/console/",
                    ),
                )
            )
        return _cached_config(team)


console.register_moved_page(
    old_path="admin/posthog/team/<int:pk>/view-cache/",
    title="The cached config view",
    url="/admin/console/tools/remote-config-cache/?team={pk}",
)
