import datetime
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from posthog.admin.console.panels import Fact, Operation, OperationHandler, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Link
from posthog.api.oauth.provisioning_review import PartnerDecisionRefused, decide_partner, partner_provisioning_status
from posthog.models.oauth import OAuthApplication, revoke_application_sessions
from posthog.models.oauth_provisioning import (
    PROVISIONING_CAPABILITIES,
    UNLIMITED_OVERRIDE,
    PartnerTier,
    ProvisioningConfig,
)
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    PartnerProvisioningStatus,
    ProvisioningReviewStatus,
)

GROWTH = Owner(name="Growth", crest="growth")
OAUTH_APPLICATIONS_TOOL_KEY = "oauth-applications"
# `active` and `disabled` are the decision, which staff change with Accept and Block, not with the other capabilities.
DECISION_FLAGS = frozenset({"active", "disabled"})
CAPABILITIES = tuple(name for name in PROVISIONING_CAPABILITIES if name not in DECISION_FLAGS)
TIER_LABELS = {
    PartnerTier.PUBLIC: "Public client",
    PartnerTier.PUBLIC_ATTESTED: "Public client, attested organization",
    PartnerTier.JWKS: "Authenticated client",
    PartnerTier.JWKS_ATTESTED: "Authenticated client, attested organization",
}
SIGNING_REQUIRED_MESSAGE = (
    "A provisioning partner must sign its requests with a private key. "
    "Make it a confidential client with a jwks_uri in Django admin first."
)


def review_page_url(review: CIMDProvisioningReview) -> str:
    tool_url = reverse("admin_console_tool", kwargs={"tool_key": OAUTH_APPLICATIONS_TOOL_KEY})
    return f"{tool_url}?{urlencode({'review': str(review.pk)})}"


def _when(value: datetime.datetime | None) -> str:
    return value.strftime("%b %-d, %Y") if value else "-"


def _label(name: str) -> str:
    return name.replace("_", " ").capitalize().replace(" api ", " API ")


KIND_LABELS = {
    "cimd": "Registered itself with a metadata document (CIMD)",
    "dcr": "Registered itself (DCR)",
    "staff": "Created by staff",
}


def app_kind(app: OAuthApplication) -> str:
    """How the app came to exist, as a key of ``KIND_LABELS``."""
    if app.is_cimd_client:
        return "cimd"
    if app.is_dcr_client:
        return "dcr"
    return "staff"


def _authentication(app: OAuthApplication) -> str:
    if app.uses_private_key_jwt_auth:
        return "Signs with a private key"
    if app.uses_client_secret_auth:
        return "Client secret"
    return "Public client, PKCE only"


STATUS_TONES: dict[PartnerProvisioningStatus, Tone | None] = {
    PartnerProvisioningStatus.NOT_A_PARTNER: None,
    PartnerProvisioningStatus.IN_REVIEW: Tone.INFO,
    PartnerProvisioningStatus.WAITING_FOR_STAFF: Tone.WARNING,
    PartnerProvisioningStatus.CHANGES_REQUESTED: Tone.INFO,
    PartnerProvisioningStatus.DECLINED: Tone.WARNING,
    PartnerProvisioningStatus.ON: Tone.SUCCESS,
    PartnerProvisioningStatus.OFF: Tone.WARNING,
    PartnerProvisioningStatus.BLOCKED: Tone.DESTRUCTIVE,
}


def provisioning_status(app: OAuthApplication, review: CIMDProvisioningReview | None) -> tuple[str, Tone | None]:
    """Whether the app can provision right now, in a few words, for the app page and the list of apps."""
    status = partner_provisioning_status(app, review)
    if status != PartnerProvisioningStatus.BLOCKED and app.provisioning.active and app.needs_organization_link:
        return "Off until it links a PostHog organization", Tone.WARNING
    if status == PartnerProvisioningStatus.ON and app.provisioning.disabled:
        return "On, though marked blocked", Tone.WARNING
    return str(status.label), STATUS_TONES[status]


def _provisioning_fact(app: OAuthApplication, review: CIMDProvisioningReview | None) -> Fact:
    label, tone = provisioning_status(app, review)
    if partner_provisioning_status(app, review) == PartnerProvisioningStatus.BLOCKED:
        label = f"{label}. Registering again does not lift it."
    return Fact(label="Provisioning", value=label, tone=tone)


def _rate_limit_endpoints() -> list[str]:
    # Deferred: budgets register when the provisioning view modules import, and pulling the ee views in when the
    # console discovers its modules would slow every process that loads the admin.
    from ee.api.agentic_provisioning import views  # noqa: F401, PLC0415
    from ee.api.agentic_provisioning.ratelimits import registered_budgets  # noqa: PLC0415

    return sorted(registered_budgets())


def _rate_limits_summary(app: OAuthApplication) -> str:
    limits = app.provisioning.rate_limits
    if not limits:
        return "The tier's defaults"
    return ", ".join(
        f"{_label(endpoint)}: {'unlimited' if value == UNLIMITED_OVERRIDE else f'{value}/hour'}"
        for endpoint, value in sorted(limits.items())
    )


class DecisionForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Goes into the audit log, and into the partner's review when it has one. The partner never sees it.",
    )
    partner_message = forms.CharField(
        required=False,
        label="Message to the partner",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=(
            "Shown to the admins of the partner's organization in PostHog, on its review. Say what they can do next. "
            "Leave it blank to show none."
        ),
    )


class CapabilitiesForm(ReasonForm):
    field_order = ("is_provisioning_partner", *CAPABILITIES, "reason")

    is_provisioning_partner = forms.BooleanField(
        required=False,
        label="Provisioning partner",
        help_text="The app can call the partner endpoints. A CIMD client becomes one by registering for provisioning.",
    )


for _name in CAPABILITIES:
    CapabilitiesForm.base_fields[_name] = forms.BooleanField(
        required=False,
        label=_label(_name),
        help_text=ProvisioningConfig.model_fields[_name].description or "",
    )


class RateLimitsForm(ReasonForm):
    def clean(self) -> dict:
        cleaned = super().clean() or {}
        for name, value in list(cleaned.items()):
            if name != "reason" and value == 0:
                # 0 is refused rather than read as unlimited. That trap is why unlimited is -1.
                self.add_error(name, "Enter a positive hourly limit, -1 for unlimited, or leave it blank.")
        return cleaned


def _rate_limits_form_class() -> type[RateLimitsForm]:
    fields: dict[str, forms.Field] = {
        endpoint: forms.IntegerField(
            required=False,
            min_value=UNLIMITED_OVERRIDE,
            label=f"{_label(endpoint)} (per hour)",
            help_text="Blank uses the tier's default, and -1 is unlimited. It outranks the tier, including blocked.",
        )
        for endpoint in _rate_limit_endpoints()
    }
    return type("RateLimitsForm", (RateLimitsForm,), {**fields, "field_order": (*fields, "reason")})


class ChangesRequestedForm(DecisionForm):
    partner_message = forms.CharField(
        label="Message to the partner",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=(
            "Shown to the admins of the partner's organization in PostHog and emailed to them. Say what to change or "
            "what to tell you. They answer with a note, which brings the review back here."
        ),
    )


DECISION_SUCCESS_MESSAGES = {
    ProvisioningReviewStatus.ACCEPTED: "Provisioning is on for {name}.",
    ProvisioningReviewStatus.DECLINED: (
        "Declined {name} and signed out every connection it had. Its organization can ask for another review."
    ),
    ProvisioningReviewStatus.CHANGES_REQUESTED: "Asked {name} for changes. Its answer brings the review back here.",
    ProvisioningReviewStatus.REJECTED: "Blocked {name} and signed out every connection it had.",
}


def _decision_handler(decision: ProvisioningReviewStatus) -> OperationHandler:
    def decide(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
        assert isinstance(obj, OAuthApplication) and form is not None
        try:
            decide_partner(
                obj,
                decision=decision,
                reason=f"Staff: {form.cleaned_data['reason']}",
                partner_message=form.cleaned_data["partner_message"],
                actor=str(getattr(request.user, "email", "")),
            )
        except PartnerDecisionRefused as refused:
            messages.error(request, str(refused))
            return HttpResponse(status=400)
        messages.success(request, DECISION_SUCCESS_MESSAGES[decision].format(name=obj.name))
        return None

    return decide


def change_capabilities(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, OAuthApplication) and form is not None
    is_partner = form.cleaned_data["is_provisioning_partner"]
    capabilities: dict[str, bool] = {name: form.cleaned_data[name] for name in CAPABILITIES}
    if not is_partner:
        # Registration reads an active non-partner as one staff vouched for in advance, and promotes it without a review.
        capabilities["active"] = False
    with transaction.atomic():
        # Checked on the locked row, so a key removed in Django admin since the page loaded is seen.
        app = OAuthApplication.objects.select_for_update().get(pk=obj.pk)
        provisioning = app.provisioning.model_copy(update=capabilities)
        if app.edit_would_break_provisioning_signature(is_provisioning_partner=is_partner, provisioning=provisioning):
            messages.error(request, SIGNING_REQUIRED_MESSAGE)
            return HttpResponse(status=400)
        app.is_provisioning_partner = is_partner
        app.provisioning = provisioning
        app.save(update_fields=["is_provisioning_partner", "_provisioning_config"])
    messages.success(request, f"Saved the capabilities of {obj.name}.")
    return None


def change_rate_limits(request: HttpRequest, obj: Model, form: forms.Form | None) -> None:
    assert isinstance(obj, OAuthApplication) and form is not None
    obj.update_provisioning_rate_limits(
        **{endpoint: form.cleaned_data[endpoint] for endpoint in _rate_limit_endpoints()}
    )
    messages.success(request, f"Saved the rate limits of {obj.name}.")


def sign_out_connections(request: HttpRequest, obj: Model, form: forms.Form | None) -> None:
    assert isinstance(obj, OAuthApplication)
    revoke_application_sessions(obj)
    messages.success(request, f"Signed out every connection of {obj.name}.")


@console.register_panel
class OAuthApplicationOverviewPanel(Panel):
    record = "oauth-application"
    key = "overview"
    title = "Overview"
    owner = GROWTH
    order = 10
    operation_keys = frozenset({"sign-out"})

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, OAuthApplication)
        facts = [
            Fact(label="Client ID", value=obj.client_id, mono=True),
            Fact(label="Kind", value=KIND_LABELS[app_kind(obj)]),
            Fact(label="Authentication", value=_authentication(obj)),
            Fact(label="Created", value=_when(obj.created)),
        ]
        if obj.organization is not None:
            facts.append(
                Fact(
                    label="Organization",
                    value=obj.organization.name,
                    href=RECORD_TYPES["organization"].url(obj.organization),
                )
            )
        elif obj.organization_link_issuer:
            facts.append(
                Fact(label="Organization", value=f"Linked to an organization at {obj.organization_link_issuer}")
            )
        if obj.is_verified:
            facts.append(Fact(label="Verified", value="Yes", tone=Tone.SUCCESS))
        if obj.is_first_party:
            facts.append(Fact(label="First party", value="Yes", tone=Tone.INFO))
        if obj.sessions_revoked_at:
            facts.append(Fact(label="Connections last signed out", value=_when(obj.sessions_revoked_at)))
        return facts

    def operations(self, obj: Model) -> list[Operation]:
        return [
            Operation(
                key="sign-out",
                label="Sign out every connection",
                handler=sign_out_connections,
                danger=True,
                form_class=ReasonForm,
                description=(
                    "Deletes every access token and revokes every refresh token of the app, for all users: CLI, MCP "
                    "and partner integrations."
                ),
                undo_hint="This cannot be undone. Each user connects the app again.",
            )
        ]


DECISION_OPERATION_KEYS = ("accept", "request-changes", "decline", "block")


def decision_operation_links(app: OAuthApplication) -> list[Link]:
    """Links to the decisions the app's page offers right now, the first one primary."""
    panel = OAuthApplicationProvisioningPanel()
    decisions = [operation for operation in panel.operations(app) if operation.key in DECISION_OPERATION_KEYS]
    return [
        Link(
            label=operation.label,
            href=reverse(
                RECORD_TYPES[panel.record].operation_url_name,
                kwargs={"pk": app.pk, "panel_key": panel.key, "operation_key": operation.key},
            ),
            primary=index == 0,
        )
        for index, operation in enumerate(decisions)
    ]


@console.register_panel
class OAuthApplicationProvisioningPanel(Panel):
    record = "oauth-application"
    key = "provisioning"
    title = "Provisioning partner"
    owner = GROWTH
    order = 20
    operation_keys = frozenset({*DECISION_OPERATION_KEYS, "capabilities", "rate-limits"})

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, OAuthApplication)
        review = getattr(obj, "provisioning_review", None)
        if not obj.is_provisioning_partner and review is None:
            return [Fact(label="Provisioning", value="Not a partner")]
        facts = [_provisioning_fact(obj, review)]
        if partner_provisioning_status(obj, review) == PartnerProvisioningStatus.WAITING_FOR_STAFF:
            facts.append(
                Fact(
                    label="Next step",
                    value="Read the review, then accept, ask for changes, decline or block the partner below.",
                )
            )
        if review is not None:
            status = ProvisioningReviewStatus(review.status)
            facts.append(
                Fact(
                    label="Review",
                    value=f"{status.label}: {review.reason}" if review.reason else status.label,
                    href=review_page_url(review),
                )
            )
        config = obj.provisioning
        granted = [_label(name) for name in CAPABILITIES if getattr(config, name)]
        facts.append(Fact(label="Capabilities", value=", ".join(granted) if granted else "None"))
        facts.append(Fact(label="Tier", value=TIER_LABELS[obj.partner_tier]))
        facts.append(Fact(label="Rate limits", value=_rate_limits_summary(obj)))
        if obj.cannot_meet_provisioning_signature:
            facts.append(
                Fact(
                    label="Signing",
                    value="Has no key to sign with, so every partner request is refused",
                    tone=Tone.DESTRUCTIVE,
                )
            )
        return facts

    def operations(self, obj: Model) -> list[Operation]:
        assert isinstance(obj, OAuthApplication)
        config = obj.provisioning
        operations = []
        review = getattr(obj, "provisioning_review", None)
        review_status = ProvisioningReviewStatus(review.status) if review is not None else None
        if obj.is_provisioning_partner and not (config.active and not config.disabled):
            description = f"Turns on provisioning for {obj.name}, so it can use the capabilities below."
            if config.disabled:
                description += " Lifts the block. Connections signed out by the block stay signed out."
            operations.append(
                Operation(
                    key="accept",
                    label="Accept partner",
                    handler=_decision_handler(ProvisioningReviewStatus.ACCEPTED),
                    form_class=DecisionForm,
                    description=description,
                )
            )
        # The partner reads these two decisions on its review and answers them there, so only an app with a review
        # gets them.
        if obj.is_provisioning_partner and review_status is not None:
            # A blocked partner was told that nothing but staff lifts the block, so it isn't asked for changes.
            if review_status != ProvisioningReviewStatus.CHANGES_REQUESTED and not config.disabled:
                operations.append(
                    Operation(
                        key="request-changes",
                        label="Ask for changes",
                        handler=_decision_handler(ProvisioningReviewStatus.CHANGES_REQUESTED),
                        form_class=ChangesRequestedForm,
                        danger=config.active,
                        undo_hint="Accept the partner here.",
                        description=(
                            f"Turns off provisioning for {obj.name} and asks its organization for changes or more "
                            "information. Its organization admins answer from organization settings, which brings the "
                            "review back to staff. Without a linked organization, nobody can answer."
                        ),
                    )
                )
            if review_status != ProvisioningReviewStatus.DECLINED:
                description = (
                    f"Turns off provisioning for {obj.name} and signs out every connection it has, without blocking "
                    "it. Its organization admins can ask for another review from organization settings."
                )
                if config.disabled:
                    description += " Lifts the block."
                operations.append(
                    Operation(
                        key="decline",
                        label="Decline partner",
                        handler=_decision_handler(ProvisioningReviewStatus.DECLINED),
                        form_class=DecisionForm,
                        danger=True,
                        undo_hint="Accept the partner here. Its users have to connect again.",
                        description=description,
                    )
                )
        if obj.is_provisioning_partner and (config.active or not config.disabled):
            operations.append(
                Operation(
                    key="block",
                    label="Block partner",
                    handler=_decision_handler(ProvisioningReviewStatus.REJECTED),
                    danger=True,
                    form_class=DecisionForm,
                    description=(
                        f"Turns off provisioning for {obj.name} and signs out every connection it has. Neither "
                        "registering again nor asking for another review lifts the block. Use it for abuse, and "
                        "decline a partner that isn't ready."
                    ),
                    undo_hint="Accept or decline the partner here. Its users have to connect again.",
                )
            )
        operations.append(
            Operation(
                key="capabilities",
                label="Change capabilities",
                handler=change_capabilities,
                danger=True,
                form_class=CapabilitiesForm,
                form_initial={
                    "is_provisioning_partner": obj.is_provisioning_partner,
                    **{name: getattr(config, name) for name in CAPABILITIES},
                },
                description=(
                    "What the partner may do once provisioning is on. Every capability is off until it is granted "
                    "here, including for a partner that registered itself."
                ),
                undo_hint="Change the capabilities back here.",
            )
        )
        if obj.is_provisioning_partner:
            operations.append(
                Operation(
                    key="rate-limits",
                    label="Change rate limits",
                    handler=change_rate_limits,
                    danger=True,
                    form_class=_rate_limits_form_class(),
                    form_initial={endpoint: config.rate_limits.get(endpoint) for endpoint in _rate_limit_endpoints()},
                    description="Hourly limits per partner endpoint. Each one replaces the budget from the tier.",
                    undo_hint="Change the limits back here.",
                )
            )
        return operations
