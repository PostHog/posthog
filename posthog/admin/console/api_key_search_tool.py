from django import forms
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table, ToolOperation
from posthog.api.secret_revocation import NON_PERSONAL_SECRET_PREFIXES
from posthog.models.oauth import find_oauth_access_token, find_oauth_refresh_token
from posthog.models.personal_api_key import find_personal_api_key
from posthog.models.project_secret_api_key import find_project_secret_api_key
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import (
    OAUTH_ACCESS_TOKEN_PREFIX,
    OAUTH_REFRESH_TOKEN_PREFIX,
    PROJECT_API_TOKEN_PREFIX,
    SECRET_API_TOKEN_PREFIX,
)


class ApiKeySearchForm(forms.Form):
    # A password input never renders the typed key back into the page, also when the form shows again.
    key = forms.CharField(
        label="Key",
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}),
        help_text="A personal API key, project secret API key, feature flags secure API key or OAuth token.",
    )


def _when(value: object) -> Cell:
    return Cell(text=str(value)) if value else Cell(text="-", muted=True)


def _user_cell(user: User | None) -> Cell:
    if user is None:
        return Cell(text="-", muted=True)
    return Cell(text=user.email, href=f"/admin/posthog/user/{user.pk}/change/")


def _team_cell(team: Team) -> Cell:
    return Cell(text=team.name, href=reverse("admin_console_team", kwargs={"pk": team.pk}))


def _personal_api_key_result(key: str) -> Table | None:
    # Legacy personal API keys predate the phx_ prefix, so any key without another known prefix is also
    # looked up as a personal API key, like authentication does.
    if key.startswith((*NON_PERSONAL_SECRET_PREFIXES, PROJECT_API_TOKEN_PREFIX)):
        return None
    found = find_personal_api_key(key)
    if found is None:
        return None
    api_key, hash_mode = found
    if api_key.scoped_organizations:
        access = "Organization access"
    elif api_key.scoped_teams:
        access = "Project access"
    else:
        access = "All access"
    change_url = f"/admin/posthog/personalapikey/{api_key.pk}/change/"
    return Table(
        columns=("Type", "Label", "User", "Scopes", "Access", "Created", "Last used", "Last rolled"),
        rows=(
            Row(
                cells=(
                    Cell(text=f"Personal API key ({hash_mode})", href=change_url),
                    Cell(text=api_key.label, href=change_url),
                    _user_cell(api_key.user),
                    Cell(text=", ".join(api_key.scopes or [])),
                    Cell(text=access),
                    _when(api_key.created_at),
                    _when(api_key.last_used_at),
                    _when(api_key.last_rolled_at),
                )
            ),
        ),
    )


def _project_secret_api_key_result(key: str) -> Table | None:
    api_key = find_project_secret_api_key(key)
    if api_key is None:
        return None
    change_url = f"/admin/posthog/projectsecretapikey/{api_key.pk}/change/"
    return Table(
        columns=("Type", "Label", "Team", "Scopes", "Created by", "Created", "Last used", "Last rolled"),
        rows=(
            Row(
                cells=(
                    Cell(text="Project secret API key", href=change_url),
                    Cell(text=api_key.label, href=change_url),
                    _team_cell(api_key.team),
                    Cell(text=", ".join(api_key.scopes or [])),
                    _user_cell(api_key.created_by),
                    _when(api_key.created_at),
                    _when(api_key.last_used_at),
                    _when(api_key.last_rolled_at),
                )
            ),
        ),
    )


def _team_secret_token_result(key: str) -> Table | None:
    # Read the row, not the team cache, so the result tells the primary and the backup token apart.
    team = Team.objects.filter(Q(secret_api_token=key) | Q(secret_api_token_backup=key)).first()
    if team is None:
        return None
    label = "Feature flags secure API key"
    if team.secret_api_token != key:
        label += " (backup)"
    return Table(columns=("Type", "Team"), rows=(Row(cells=(Cell(text=label), _team_cell(team))),))


def _oauth_access_token_result(key: str) -> Table | None:
    token = find_oauth_access_token(key)
    if token is None:
        return None
    application = token.application
    return Table(
        columns=("Type", "User", "Application", "Expires", "Scope", "Created"),
        rows=(
            Row(
                cells=(
                    Cell(text="OAuth access token", href=f"/admin/posthog/oauthaccesstoken/{token.pk}/change/"),
                    _user_cell(token.user),
                    Cell(text=application.name, href=f"/admin/posthog/oauthapplication/{application.pk}/change/")
                    if application is not None
                    else Cell(text="-", muted=True),
                    _when(token.expires),
                    Cell(text=token.scope or ""),
                    _when(token.created),
                )
            ),
        ),
    )


def _oauth_refresh_token_result(key: str) -> Table | None:
    token = find_oauth_refresh_token(key)
    if token is None:
        return None
    application = token.application
    return Table(
        columns=("Type", "User", "Application", "Revoked", "Created"),
        rows=(
            Row(
                cells=(
                    Cell(text="OAuth refresh token", href=f"/admin/posthog/oauthrefreshtoken/{token.pk}/change/"),
                    _user_cell(token.user),
                    Cell(text=application.name, href=f"/admin/posthog/oauthapplication/{application.pk}/change/")
                    if application is not None
                    else Cell(text="-", muted=True),
                    Cell(text="Yes" if token.revoked else "No"),
                    _when(token.created),
                )
            ),
        ),
    )


def find_key(key: str) -> Table | None:
    personal = _personal_api_key_result(key)
    if personal is not None:
        return personal
    if key.startswith(SECRET_API_TOKEN_PREFIX):
        return _project_secret_api_key_result(key) or _team_secret_token_result(key)
    if key.startswith(OAUTH_ACCESS_TOKEN_PREFIX):
        return _oauth_access_token_result(key)
    if key.startswith(OAUTH_REFRESH_TOKEN_PREFIX):
        return _oauth_refresh_token_result(key)
    return None


def search_key(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    # The result shows on the response to the POST, so the key never appears in a URL or the browser history.
    result = find_key(form.cleaned_data["key"])
    if result is None:
        return Page(blocks=(Notice(text="No key matches. Check that the whole key was pasted, without spaces."),))
    return Page(blocks=(result,))


@console.register_tool
class ApiKeySearchTool(ConsoleTool):
    key = "api-key-search"
    title = "API key search"
    owner = DEV_EXPERIENCE
    group = "Data"
    description = "Finds who owns an API key or OAuth token, from the full key."

    def page(self, request: HttpRequest) -> Page:
        return Page(
            blocks=(
                Notice(
                    text=(
                        "Search with the full key. The result shows the key's owner and where to change it, "
                        "never the key itself."
                    )
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="search",
                label="Search for a key",
                handler=search_key,
                description="Looks the key up. Changes nothing.",
                form_class=ApiKeySearchForm,
            )
        ]


# The old page took the key in a POST body, so a bookmark carries no key and none lands in the new URL.
console.register_moved_page(
    old_path="admin/apikeysearch", title="API key search", url="/admin/console/tools/api-key-search/"
)
