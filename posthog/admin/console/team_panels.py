from decimal import Decimal

from django import forms
from django.db.models import Model

from posthog.admin.admins.team_admin import TeamAdmin
from posthog.admin.console.bridge import AdminViewBridge
from posthog.admin.console.panels import Fact, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.models.activity_logging.activity_log import ActivityLog
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
                handler=AdminViewBridge(Team, TeamAdmin.rebuild_cache),
                description="Recomputes the remote config for this team and writes it to Redis and S3.",
            )
        ]


AI_GATEWAY = Owner(name="AI gateway", crest="ai-gateway")


class AddCreditForm(forms.Form):
    amount_usd = forms.DecimalField(label="Amount (USD)", min_value=Decimal("0.01"), decimal_places=2)
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Shown in the top-up history.")


class SetApiTokenForm(forms.Form):
    new_token = forms.CharField(label="New API token")
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")


RECENT_TOP_UPS = 3


@console.register_panel
class AIGatewayPanel(Panel):
    record = "team"
    key = "ai-gateway"
    title = "AI gateway"
    owner = AI_GATEWAY

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Team)
        if obj.llm_gateway_revoked_at:
            access = Fact(label="Access", value="Revoked", tone=Tone.DESTRUCTIVE)
        elif obj.llm_gateway_enabled_at:
            access = Fact(label="Access", value="Enrolled", tone=Tone.SUCCESS)
        else:
            access = Fact(label="Access", value="Not enrolled", tone=Tone.DEFAULT)
        facts = [access]
        if obj.llm_gateway_enabled_at:
            facts.append(Fact(label="Enrolled since", value=obj.llm_gateway_enabled_at.strftime("%b %-d, %Y")))
        # The wallet balance is a blocking call to the gateway, so the page shows the local top-up log instead.
        top_ups = (
            ActivityLog.objects.filter(scope="AIGatewayCredit", team_id=obj.pk, activity="credit_added")
            .select_related("user")
            .order_by("-created_at")[:RECENT_TOP_UPS]
        )
        for entry in top_ups:
            context = (entry.detail or {}).get("context", {})
            who = entry.user.email if entry.user else "unknown"
            facts.append(
                Fact(
                    label=f"Top-up {entry.created_at.strftime('%b %-d')}",
                    value=f"${context.get('amount_usd', '?')} by {who}: {context.get('reason', '')}",
                )
            )
        return facts

    def operations(self, obj: Model) -> list[Operation]:
        assert isinstance(obj, Team)
        operations = [
            Operation(
                key="add-credit",
                label="Add credit",
                handler=AdminViewBridge(Team, TeamAdmin.add_ai_gateway_credit_view),
                description="Adds USD credit to the team's gateway wallet.",
                form_class=AddCreditForm,
            )
        ]
        if obj.llm_gateway_enabled_at is None:
            operations.append(
                Operation(
                    key="enable",
                    label="Enable access",
                    handler=AdminViewBridge(Team, TeamAdmin.enable_ai_gateway_view),
                )
            )
        if obj.llm_gateway_revoked_at is None:
            operations.append(
                Operation(
                    key="revoke",
                    label="Revoke access",
                    handler=AdminViewBridge(Team, TeamAdmin.revoke_ai_gateway_view),
                    danger=True,
                    description="Blocks the team's gateway requests until the revoke is cleared.",
                    form_class=ReasonForm,
                )
            )
        else:
            operations.append(
                Operation(
                    key="clear-revoke",
                    label="Clear revoke",
                    handler=AdminViewBridge(Team, TeamAdmin.clear_ai_gateway_revoke_view),
                )
            )
        return operations


@console.register_panel
class ApiTokenPanel(Panel):
    record = "team"
    key = "api-token"
    title = "Project API token"
    owner = DEV_EXPERIENCE
    danger = True

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Team)
        return [Fact(label="Current token", value=obj.api_token, mono=True)]

    def operations(self, obj: Model) -> list[Operation]:
        return [
            Operation(
                key="set",
                label="Set API token",
                handler=AdminViewBridge(Team, TeamAdmin.set_api_token_view),
                danger=True,
                description="SDKs that still send the old token stop reaching this team.",
                form_class=SetApiTokenForm,
            )
        ]
