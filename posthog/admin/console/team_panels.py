from typing import cast

from django import forms
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from posthog.admin.console.panels import Fact, Operation, Owner, Panel, Tone
from posthog.admin.console.registry import console
from posthog.helpers.impersonation import is_impersonated
from posthog.models.organization import OrganizationMembership
from posthog.models.remote_config import RemoteConfig
from posthog.models.team.team import Team
from posthog.models.user import User

# The console shell owns the core panels until a team claims one.
DEV_EXPERIENCE = Owner(name="Dev experience", crest="dev-experience")


@console.register_panel
class TeamOverviewPanel(Panel):
    record = "team"
    key = "overview"
    title = "Overview"
    owner = DEV_EXPERIENCE
    order = 10

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Team)
        owner = (
            OrganizationMembership.objects.filter(
                organization_id=obj.organization_id, level=OrganizationMembership.Level.OWNER
            )
            .select_related("user")
            .order_by("joined_at")
            .first()
        )
        return [
            Fact(
                label="Owner", value=owner.user.email, href=reverse("admin_console_user", kwargs={"pk": owner.user_id})
            )
            if owner
            else Fact(label="Owner", value="No owner"),
            Fact(label="Members", value=str(obj.organization.members.count())),
            Fact(
                label="Project",
                value=str(obj.project_id),
                mono=True,
                href=reverse("admin_console_project", kwargs={"pk": obj.project_id}),
            ),
            Fact(label="Created", value=obj.created_at.strftime("%b %-d, %Y")),
            Fact(label="Timezone", value=obj.timezone),
            Fact(
                label="Ingested events",
                value="Yes" if obj.ingested_event else "Not yet",
                tone=Tone.SUCCESS if obj.ingested_event else Tone.WARNING,
            ),
        ]


@console.register_panel
class RemoteConfigPanel(Panel):
    record = "team"
    key = "remote-config"
    title = "Remote config cache"
    owner = DEV_EXPERIENCE
    order = 20

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Team)
        tool_url = reverse("admin_console_tool", kwargs={"tool_key": "remote-config-cache"})
        return [
            Fact(
                label="Cache", value="SDKs read the team's config from this cache. It rebuilds when the config changes."
            ),
            Fact(label="Cache key", value=RemoteConfig.get_hypercache().get_cache_key(obj.api_token), mono=True),
            Fact(label="Cached config", value="View the JSON", href=f"{tool_url}?team={obj.pk}"),
        ]

    def operations(self, obj: Model) -> list[Operation]:
        return [
            Operation(
                key="rebuild",
                label="Rebuild cache",
                handler=rebuild_remote_config_cache,
                description="Recomputes the remote config for this team and writes it to Redis and S3.",
            )
        ]


class SetApiTokenForm(forms.Form):
    new_token = forms.CharField(label="New API token")
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")


def rebuild_remote_config_cache(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, Team)
    RemoteConfig.rebuild_cache_for_team(obj)
    messages.success(request, f"Cache rebuilt for team '{obj.name}' (token: {obj.api_token}).")
    return None


def set_api_token(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, Team) and form is not None
    try:
        with transaction.atomic():
            obj.set_token_and_save(
                new_token=form.cleaned_data["new_token"],
                user=cast(User, request.user),
                is_impersonated_session=is_impersonated(request),
            )
    except ValueError as error:
        messages.error(request, str(error))
        return HttpResponse(status=400)
    except IntegrityError:
        messages.error(request, "Another team already owns this API token. Pick a different value.")
        return HttpResponse(status=400)
    messages.success(request, f"API token updated for team '{obj.name}'.")
    return None


@console.register_panel
class ApiTokenPanel(Panel):
    record = "team"
    key = "api-token"
    title = "Project API token"
    owner = DEV_EXPERIENCE
    operation_keys = frozenset({"set"})
    order = 30
    danger = True

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Team)
        return [Fact(label="Current token", value=obj.api_token, mono=True)]

    def operations(self, obj: Model) -> list[Operation]:
        return [
            Operation(
                key="set",
                label="Set API token",
                handler=set_api_token,
                danger=True,
                description="SDKs that still send the old token stop reaching this team.",
                form_class=SetApiTokenForm,
                undo_hint="This cannot be undone automatically. To go back, set the old token again.",
            )
        ]


# Old Django admin URLs of team actions that moved. Staff keep bookmarks to them, query parameters included.
console.register_moved_action(
    old_path="admin/posthog/team/<int:pk>/set-api-token/", record="team", target="api-token/set/"
)
console.register_moved_action(
    old_path="admin/posthog/team/<int:pk>/rebuild-cache/", record="team", target="#panel-remote-config"
)
