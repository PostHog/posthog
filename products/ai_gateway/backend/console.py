import uuid
from decimal import Decimal
from typing import cast

from django import forms
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse

from posthog.admin.console.panels import Fact, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.helpers.impersonation import is_impersonated
from posthog.models.team.team import Team
from posthog.models.user import User

from products.ai_gateway.backend.facade import api
from products.ai_gateway.backend.facade.contracts import TeamCreditRefused
from products.ai_gateway.backend.facade.enums import TeamAccessAction

AI_GATEWAY = Owner(name="AI gateway", crest="ai-gateway")
RECENT_TOP_UPS = 3

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
