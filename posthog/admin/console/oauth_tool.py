import re
from uuid import UUID

from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table, ToolOperation
from posthog.models.oauth import OAuthApplication, revoke_application_sessions
from posthog.utils import pluralize


class RevokeSessionsForm(forms.Form):
    MAX_APPLICATIONS = 100

    applications = forms.CharField(
        label="Application IDs",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=(
            "One application ID per line, or separated by commas. Pick applications in the Django admin list and "
            "choose Revoke all sessions to fill this in."
        ),
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")

    def clean_applications(self) -> list[UUID]:
        tokens = re.findall(r"[^,\s]+", self.cleaned_data["applications"])
        if not tokens:
            raise forms.ValidationError("Enter at least one application ID.")
        if len(tokens) > self.MAX_APPLICATIONS:
            raise forms.ValidationError(f"Enter {self.MAX_APPLICATIONS} application IDs or fewer.")
        application_ids: list[UUID] = []
        for token in tokens:
            try:
                application_ids.append(UUID(token))
            except ValueError:
                raise forms.ValidationError(f"{token} is not an application ID.")
        return list(dict.fromkeys(application_ids))


def _applications(form: forms.Form) -> list[OAuthApplication]:
    return list(OAuthApplication.objects.filter(id__in=form.cleaned_data["applications"]).order_by("name"))


def preview_revoke_sessions(request: HttpRequest, form: forms.Form) -> Page:
    applications = _applications(form)
    if not applications:
        form.add_error("applications", "No application matches these IDs.")
        return Page(blocks=())
    return Page(
        blocks=(
            Notice(
                text=(
                    f"Signs out every connection of {pluralize(len(applications), 'application')} across all "
                    "users: CLI, MCP and partner integrations. Each connection authorizes again under the current "
                    "scopes."
                )
            ),
            Table(
                columns=("Application", "Client ID"),
                rows=tuple(
                    Row(
                        cells=(
                            Cell(text=application.name),
                            Cell(text=application.client_id, mono=True),
                        )
                    )
                    for application in applications
                ),
            ),
        )
    )


def revoke_sessions(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    applications = _applications(form)
    for application in applications:
        revoke_application_sessions(application)
    messages.success(request, f"Revoked all sessions for {pluralize(len(applications), 'application')}.")
    return None


@console.register_tool
class OAuthSessionsTool(ConsoleTool):
    key = "oauth-sessions"
    title = "Revoke OAuth app sessions"
    owner = DEV_EXPERIENCE
    group = "Access"
    description = "Signs out every connection of an OAuth application, after a preview."

    def page(self, request: HttpRequest) -> Page:
        return Page(
            blocks=(
                Notice(
                    text=(
                        "Revoking sessions makes every connection of an application authorize again, for example "
                        "after its scopes were narrowed. You see the applications before anything changes."
                    ),
                    link_text="OAuth applications in Django admin",
                    href=reverse("admin:posthog_oauthapplication_changelist"),
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="revoke",
                label="Revoke all sessions",
                handler=revoke_sessions,
                preview=preview_revoke_sessions,
                danger=True,
                description=(
                    "Deletes every access token and revokes every refresh token of the applications, for all users."
                ),
                form_class=RevokeSessionsForm,
                # The Django admin action sends staff here with the applications they picked.
                form_initial={"applications": "\n".join(request.GET.getlist("application"))},
                undo_hint="This cannot be undone. Each user connects the application again.",
            )
        ]
