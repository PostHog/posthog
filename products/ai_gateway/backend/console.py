import uuid
from decimal import Decimal
from typing import cast

from django import forms
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from posthog.admin.console.panels import Fact, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table
from posthog.helpers.impersonation import is_impersonated
from posthog.models.team.team import Team
from posthog.models.user import User

from products.ai_gateway.backend.facade import api
from products.ai_gateway.backend.facade.contracts import TeamCreditRefused, TeamWallet, TeamWalletUnavailable
from products.ai_gateway.backend.facade.enums import TeamAccessAction

AI_GATEWAY = Owner(name="AI gateway", crest="ai-gateway")
RECENT_TOP_UPS = 3
WALLET_TOOL_KEY = "ai-gateway-wallet"

_ACCESS_MESSAGES = {
    TeamAccessAction.ENABLE: ("Enabled AI gateway access for team '{name}'.", "Team '{name}' was already enabled."),
    TeamAccessAction.REVOKE: ("Revoked AI gateway access for team '{name}'.", "Team '{name}' was already revoked."),
    TeamAccessAction.UNREVOKE: ("Cleared the AI gateway revoke for team '{name}'.", "Team '{name}' was not revoked."),
}


class AddCreditForm(forms.Form):
    amount_usd = forms.DecimalField(label="Amount (USD)", min_value=Decimal("0.01"), decimal_places=2)
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Shown in the top-up history.")


class TeamAccessHandler:
    def __init__(self, action: TeamAccessAction) -> None:
        self.action = action

    def __call__(self, request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
        assert isinstance(obj, Team)
        change = api.change_team_access(obj.pk, self.action)
        changed_message, unchanged_message = _ACCESS_MESSAGES[self.action]
        if change.changed:
            messages.success(request, changed_message.format(name=obj.name))
        else:
            messages.info(request, unchanged_message.format(name=obj.name))
        return None


def add_credit(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, Team) and form is not None
    try:
        result = api.add_team_credit(
            obj.pk,
            form.cleaned_data["amount_usd"],
            form.cleaned_data["reason"],
            form_nonce=request.POST.get("form_nonce") or str(uuid.uuid4()),
            actor=cast(User, request.user),
            was_impersonated=is_impersonated(request),
        )
    except TeamCreditRefused as refused:
        messages.error(request, refused.detail)
        return HttpResponse(status=400)
    if result.duplicate:
        messages.info(request, f"Idempotent replay, no new credit. Team '{obj.name}' balance: ${result.balance_usd}.")
    else:
        messages.success(
            request, f"Added ${result.amount_usd} to team '{obj.name}'. New balance: ${result.balance_usd}."
        )
    return None


@console.register_panel
class AIGatewayPanel(Panel):
    record = "team"
    key = "ai-gateway"
    title = "AI gateway"
    owner = AI_GATEWAY
    operation_keys = frozenset({"add-credit", "enable", "revoke", "clear-revoke"})

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
        # The wallet balance is a blocking call to the gateway, so the team page links to it and shows the local
        # top-up log instead.
        facts.append(
            Fact(
                label="Wallet",
                value="Balance and recent ledger",
                href=f"{reverse('admin_console_tool', kwargs={'tool_key': WALLET_TOOL_KEY})}?team={obj.pk}",
            )
        )
        for top_up in api.recent_team_credits(obj.pk, RECENT_TOP_UPS):
            facts.append(
                Fact(
                    label=f"Top-up {top_up.created_at.strftime('%b %-d')}",
                    value=f"${top_up.amount_usd} by {top_up.actor_email or 'unknown'}: {top_up.reason}",
                )
            )
        return facts

    def operations(self, obj: Model) -> list[Operation]:
        assert isinstance(obj, Team)
        operations = [
            Operation(
                key="add-credit",
                label="Add credit",
                handler=add_credit,
                description="Adds USD credit to the team's gateway wallet.",
                form_class=AddCreditForm,
            )
        ]
        if obj.llm_gateway_enabled_at is None:
            operations.append(
                Operation(
                    key="enable",
                    label="Enable access",
                    handler=TeamAccessHandler(TeamAccessAction.ENABLE),
                    description="Lets the team send requests through the AI gateway.",
                )
            )
        if obj.llm_gateway_revoked_at is None:
            operations.append(
                Operation(
                    key="revoke",
                    label="Revoke access",
                    handler=TeamAccessHandler(TeamAccessAction.REVOKE),
                    danger=True,
                    description="Blocks the team's gateway requests until the revoke is cleared.",
                    form_class=ReasonForm,
                    undo_hint="To undo, use Clear revoke in the AI gateway panel.",
                )
            )
        else:
            operations.append(
                Operation(
                    key="clear-revoke",
                    label="Clear revoke",
                    handler=TeamAccessHandler(TeamAccessAction.UNREVOKE),
                    description="Lets the team's gateway requests through again.",
                )
            )
        return operations


def _wallet_balance(wallet: TeamWallet) -> str:
    if not wallet.has_ledger:
        return "This region's gateway has no ledger, so there is no wallet to show."
    if not wallet.known:
        return "The team has no gateway account yet. The balance is $0.00 until the first credit or spend."
    return f"Balance: ${wallet.balance_usd}"


@console.register_tool
class AIGatewayWalletTool(ConsoleTool):
    key = WALLET_TOOL_KEY
    title = "AI gateway wallet"
    owner = AI_GATEWAY
    group = "Billing"
    description = "The gateway balance and recent ledger entries of one team."

    def page(self, request: HttpRequest) -> Page:
        team_id = request.GET.get("team", "")
        if not team_id.isdecimal():
            return Page(blocks=(Notice(text="Open a team's wallet from the AI gateway panel on the team's page."),))
        team_url = reverse("admin_console_team", kwargs={"pk": int(team_id)})
        try:
            wallet = api.team_wallet(int(team_id))
        except TeamWalletUnavailable as unavailable:
            return Page(blocks=(Notice(text=unavailable.detail, link_text="Back to the team", href=team_url),))
        blocks: list[Notice | Table] = [
            Notice(text=f"Team {team_id}. {_wallet_balance(wallet)}", link_text="Back to the team", href=team_url)
        ]
        if wallet.has_ledger:
            blocks.append(
                Table(
                    columns=("When", "Kind", "Amount", "Reference"),
                    rows=tuple(
                        Row(
                            cells=(
                                Cell(text=entry.when),
                                Cell(text=entry.kind),
                                Cell(text=entry.amount),
                                Cell(text=entry.reference, mono=True),
                            )
                        )
                        for entry in wallet.recent
                    ),
                    empty_text="No ledger entries yet.",
                )
            )
        return Page(blocks=tuple(blocks))


# Old Django admin URLs of team actions that moved. Staff keep bookmarks to them, query parameters included.
for old, target in {
    "add-ai-gateway-credit": "ai-gateway/add-credit/",
    "enable-ai-gateway": "#panel-ai-gateway",
    "revoke-ai-gateway": "#panel-ai-gateway",
    "clear-ai-gateway-revoke": "#panel-ai-gateway",
}.items():
    console.register_moved_action(old_path=f"admin/posthog/team/<int:pk>/{old}/", record="team", target=target)
console.register_moved_page(
    old_path="admin/posthog/team/<int:pk>/ai-gateway-wallet/",
    title="The AI gateway wallet",
    url="/admin/console/tools/ai-gateway-wallet/?team={pk}",
)
