from django.db.models import Model

from posthog.admin.console.bridge import AdminViewBridge
from posthog.admin.console.panels import Fact, Operation, Owner, Panel, Tone
from posthog.admin.console.registry import console
from posthog.models.team.team import Team

# The console shell owns the core panels until a team claims one.
DEV_EXPERIENCE = Owner(name="Dev experience", crest="dev-experience")


@console.register_panel
class TeamOverviewPanel(Panel):
    record = "team"
    key = "overview"
    title = "Overview"
    owner = DEV_EXPERIENCE

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Team)
        return [
            Fact(label="Organization", value=obj.organization.name),
            Fact(label="Project", value=str(obj.project_id), mono=True),
            Fact(label="Created", value=obj.created_at.strftime("%b %-d, %Y")),
            Fact(label="Timezone", value=obj.timezone),
            Fact(
                label="Ingested events",
                value="Yes" if obj.ingested_event else "Not yet",
                tone=Tone.SUCCESS if obj.ingested_event else Tone.WARNING,
            ),
            Fact(label="API token", value=obj.api_token, mono=True),
        ]


@console.register_panel
class RemoteConfigPanel(Panel):
    record = "team"
    key = "remote-config"
    title = "Remote config cache"
    owner = DEV_EXPERIENCE

    def facts(self, obj: Model) -> list[Fact]:
        return [Fact(label="Cache", value="Served from the hypercache, rebuilt on config changes")]

    def operations(self, obj: Model) -> list[Operation]:
        return [
            Operation(
                key="rebuild",
                label="Rebuild cache",
                handler=AdminViewBridge(Team, "rebuild_cache"),
                description="Recomputes the remote config for this team and writes it to Redis and S3.",
            )
        ]
