from datetime import UTC, datetime
from typing import cast

from django import forms
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse

import structlog

from posthog.admin.console.organization_shutdown import (
    STOP_NOTICE,
    UNDO_HINT,
    OrganizationShutdownForm,
    find_background_work,
    inventory_table,
    planned_action,
    result_page,
    shut_down_organizations,
    take_inventory,
)
from posthog.admin.console.panels import MAX_FACTS_PER_PANEL, Fact, Operation, Owner, Panel, Tone
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Notice, Page
from posthog.models.organization import Organization
from posthog.models.user import User

from ee.billing.quota_limiting import QuotaResource

logger = structlog.get_logger(__name__)

BILLING = Owner(name="Billing", crest="billing", staff_group="Billing Team")


@console.register_panel
class OrganizationOverviewPanel(Panel):
    record = "organization"
    key = "overview"
    title = "Overview"
    owner = None
    order = 10

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Organization)
        if obj.is_active is False:
            status = Fact(
                label="Status", value=f"Deactivated: {obj.is_not_active_reason or 'no reason'}", tone=Tone.DESTRUCTIVE
            )
        else:
            status = Fact(label="Status", value="Active", tone=Tone.SUCCESS)
        facts = [
            status,
            Fact(label="Members", value=str(obj.members.count())),
            Fact(label="Created", value=obj.created_at.strftime("%b %-d, %Y")),
        ]
        if obj.is_pending_deletion:
            facts.append(Fact(label="Deletion", value="Pending", tone=Tone.WARNING))
        return facts


@console.register_panel
class OrganizationTeamsPanel(Panel):
    record = "organization"
    key = "teams"
    title = "Teams"
    owner = None
    order = 20

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Organization)
        team_record = RECORD_TYPES["team"]
        teams = list(obj.teams.order_by("id").only("id", "name")[: MAX_FACTS_PER_PANEL + 1])
        if not teams:
            return [Fact(label="Teams", value="This organization has no teams.")]
        shown = teams if len(teams) <= MAX_FACTS_PER_PANEL else teams[: MAX_FACTS_PER_PANEL - 1]
        facts = [
            Fact(label=team.name, value=f"Team {team.pk}", mono=True, href=team_record.url(team)) for team in shown
        ]
        if len(shown) < len(teams):
            hidden = obj.teams.count() - len(shown)
            facts.append(Fact(label="More", value=f"{hidden} more teams. Look up the organization name to see all."))
        return facts


def preview_shutdown(request: HttpRequest, obj: Model, form: forms.Form) -> Page:
    assert isinstance(obj, Organization)
    stop_background_work = form.cleaned_data["stop_background_work"]
    action = planned_action(obj, stop_background_work=stop_background_work)
    blocks = [
        Notice(
            text=f"Deactivates the organization with the reason: {form.cleaned_data['resolved_reason']}"
            if obj.is_active is not False
            else "The organization is already inactive and keeps its reason."
        )
    ]
    if stop_background_work:
        blocks.append(Notice(text=STOP_NOTICE))
    return Page(blocks=(*blocks, inventory_table([take_inventory(obj)], {obj.id: action})))


def shut_down(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | Page | None:
    assert isinstance(obj, Organization) and form is not None
    stop_background_work = form.cleaned_data["stop_background_work"]
    results = shut_down_organizations(
        [obj.id],
        reason=form.cleaned_data["resolved_reason"],
        stop_background_work=stop_background_work,
        triggered_by=cast(User, request.user).email,
    )
    if stop_background_work:
        return result_page(results)
    if results and results[0].deactivated:
        messages.success(request, f"Deactivated '{obj.name}'.")
    else:
        messages.warning(request, f"'{obj.name}' was already inactive. Its reason did not change.")
    return None


@console.register_panel
class OrganizationBackgroundWorkPanel(Panel):
    record = "organization"
    key = "background-work"
    title = "Background work"
    owner = None
    order = 25

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Organization)
        listing = find_background_work(list(obj.teams.values_list("id", flat=True)))
        facts = [Fact(label=work.label, value=str(len(work.ids))) for work in listing.running]
        facts += [Fact(label=kind, value="Could not list", tone=Tone.WARNING) for kind in listing.unlisted]
        if not facts:
            return [Fact(label="Running", value="Nothing", tone=Tone.SUCCESS)]
        if len(facts) <= MAX_FACTS_PER_PANEL:
            return facts
        shown = facts[: MAX_FACTS_PER_PANEL - 1]
        more = Fact(label="More", value=f"{len(facts) - len(shown)} more kinds. The shutdown preview lists all.")
        return [*shown, more]

    def operations(self, obj: Model) -> list[Operation]:
        return [
            Operation(
                key="shut-down",
                label="Shut down organization",
                handler=shut_down,
                preview=preview_shutdown,
                danger=True,
                description=(
                    "Deactivates the organization and stops its background work. Members see the reason. "
                    "Nothing is deleted."
                ),
                form_class=OrganizationShutdownForm,
                undo_hint=UNDO_HINT,
                pending_label="Shutting down. This can take a minute...",
            )
        ]


class QuotaLimits:
    """Which products are quota limited right now, read from the limiter cache that ingestion checks."""

    @staticmethod
    def limited(organization: Organization) -> dict[QuotaResource, int | None]:
        limited: dict[QuotaResource, int | None] = {}
        for resource_value, info in organization.get_limited_products().items():
            if info["is_limited_in_redis"]:
                limited[QuotaResource(resource_value)] = info["redis_quota_limited_until"]
        return limited


_RESOURCE_CHOICES = [(resource.value, resource.value) for resource in QuotaResource]


class LimitProductForm(forms.Form):
    resource = forms.ChoiceField(label="Product", choices=_RESOURCE_CHOICES)
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")


class UnlimitProductForm(forms.Form):
    resource = forms.ChoiceField(label="Product", choices=_RESOURCE_CHOICES)


def limit_product(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, Organization) and form is not None
    resource = QuotaResource(form.cleaned_data["resource"])
    try:
        obj.limit_product_until_end_of_billing_cycle(resource)
    except RuntimeError as error:
        messages.error(request, f"Could not limit {resource.value}: {error}.")
        return HttpResponse(status=400)
    messages.success(request, f"Limited {resource.value} for '{obj.name}' until the end of the billing period.")
    return None


def unlimit_product(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, Organization) and form is not None
    resource = QuotaResource(form.cleaned_data["resource"])
    obj.unlimit_product(resource)
    messages.success(request, f"Removed the {resource.value} limit for '{obj.name}'.")
    return None


def sync_members_to_billing(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    from posthog.tasks.sync_billing import sync_members_to_billing as sync_task  # noqa: PLC0415 — Celery task module

    assert isinstance(obj, Organization)
    sync_task.delay(obj.id)
    messages.success(request, f"Queued a member sync to billing for '{obj.name}'.")
    return None


@console.register_panel
class BillingPanel(Panel):
    record = "organization"
    key = "billing"
    title = "Billing"
    owner = BILLING
    order = 30

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Organization)
        limited = QuotaLimits.limited(obj)
        if not limited:
            return [Fact(label="Limited products", value="None", tone=Tone.SUCCESS)]
        ordered = sorted(limited.items(), key=lambda item: item[0].value)
        # Past the panel's fact limit, the last fact counts the rest, so a long list never looks complete when it is not.
        shown = ordered if len(ordered) <= MAX_FACTS_PER_PANEL else ordered[: MAX_FACTS_PER_PANEL - 1]
        facts = []
        for resource, until in shown:
            when = datetime.fromtimestamp(until, tz=UTC).strftime("%b %-d, %Y") if until else "no end date"
            facts.append(Fact(label=resource.value, value=f"Limited until {when}", tone=Tone.WARNING))
        if len(shown) < len(ordered):
            facts.append(
                Fact(
                    label="More limits",
                    value=f"{len(ordered) - len(shown)} more products are limited. The raw record in Django admin lists every one.",
                    tone=Tone.WARNING,
                )
            )
        return facts

    def operations(self, obj: Model) -> list[Operation]:
        return [
            Operation(
                key="limit",
                label="Limit a product",
                handler=limit_product,
                danger=True,
                description="Drops the product's new data for every team in the organization until the billing period ends.",
                form_class=LimitProductForm,
                undo_hint="To undo, use Remove a limit in the Billing panel.",
            ),
            Operation(
                key="unlimit",
                label="Remove a limit",
                handler=unlimit_product,
                description="Lets the product's data in again for every team in the organization.",
                form_class=UnlimitProductForm,
            ),
            Operation(
                key="sync-members",
                label="Sync members to billing",
                handler=sync_members_to_billing,
                description="Sends the current member list to the billing service.",
            ),
        ]


for old in ("limit-product", "unlimit-product", "sync-to-billing"):
    console.register_moved_action(
        old_path=f"admin/posthog/organization/<uuid:pk>/{old}/", record="organization", target="#panel-billing"
    )
