"""Constants and small helpers shared across the GitHub callback modules."""

import re
from enum import StrEnum
from typing import Any, Literal, Self
from urllib.parse import parse_qsl, urlencode, urlparse

from django.conf import settings

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError
from rest_framework.exceptions import ValidationError as ApiValidationError

from posthog.models.instance_setting import get_instance_settings

# Server-side state cache used by the personal GitHub linking flow (the install
# callback and the OAuth-only fast paths). Keys are written when a flow starts
# and consumed when GitHub redirects back to us.
GITHUB_INSTALL_STATE_CACHE_PREFIX = "github_user_install_state:"
GITHUB_INSTALL_STATE_TTL_SECONDS = 10 * 60

GITHUB_INSTALLATION_ID_PATTERN = re.compile(r"\d{1,20}")

GITHUB_AUTHORIZE_STATE_CACHE_TTL_SECONDS = 60 * 15
GITHUB_UNIFIED_AUTHORIZE_CACHE_PREFIX = "github_authorize:"
GITHUB_UNIFIED_AUTHORIZE_PENDING_PREFIX = "github_authorize_pending:"

ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH = "/account-connected/github-integration"
PERSONAL_INTEGRATIONS_SETTINGS_PATH = "/settings/user-personal-integrations"
MOBILE_GITHUB_CALLBACK_URL = "posthog://github/callback"
# ``connect_from`` values for first-party clients that use the lightweight app
# linking flow (OAuth-only when the team already has the GitHub App installed,
# otherwise discover/install) and return to a client-specific destination.
APP_CONNECT_FROM_VALUES = ("posthog_code", "posthog_mobile", "slack")


class FlowKind(StrEnum):
    TEAM_INSTALL = "team_install"
    TEAM_UPDATE = "team_update"
    TEAM_OAUTH = "team_oauth"
    PERSONAL_INSTALL = "personal_install"
    PERSONAL_OAUTH = "personal_oauth"
    PERSONAL_UPDATE = "personal_update"
    OAUTH_DISCOVER = "oauth_discover"

    @property
    def is_oauth_redirect(self) -> bool:
        """OAuth returned to /complete/github-link/ — code exchange uses redirect_uri."""
        return self in (FlowKind.PERSONAL_OAUTH, FlowKind.OAUTH_DISCOVER, FlowKind.TEAM_OAUTH)

    @property
    def discovers_installations(self) -> bool:
        return self is FlowKind.OAUTH_DISCOVER

    @property
    def creates_team_integration(self) -> bool:
        return self is FlowKind.TEAM_OAUTH

    @property
    def is_personal(self) -> bool:
        return self in (
            FlowKind.PERSONAL_INSTALL,
            FlowKind.PERSONAL_OAUTH,
            FlowKind.PERSONAL_UPDATE,
            FlowKind.OAUTH_DISCOVER,
        )


def team_id_from_next_url(next_url: str) -> int | None:
    if not next_url:
        return None
    path_parts = [part for part in urlparse(next_url).path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] == "project":
        try:
            return int(path_parts[1])
        except ValueError:
            pass
    return None


def is_personal_github_setup_state(state_raw: str | None) -> bool:
    """True when GitHub's Setup URL callback belongs to a personal UserIntegration flow."""
    if not state_raw:
        return False
    return dict(parse_qsl(state_raw)).get("source") == "user_integration"


class GitHubAuthorizeState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    token: str
    flow: FlowKind
    user_id: int
    team_id: int | None = None
    installation_id: str | None = None
    next_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("next_url", "next"),
        serialization_alias="next",
    )
    connect_from: str | None = None

    @classmethod
    def from_cache(cls, token: str, payload: dict[str, Any]) -> Self:
        return cls.model_validate({**payload, "token": token})

    @classmethod
    def try_from_cache(cls, token: str, payload: dict[str, Any]) -> Self | None:
        try:
            return cls.from_cache(token, payload)
        except ValidationError:
            return None

    def cache_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True, by_alias=True)


class CallbackContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: Literal["setup_url", "oauth_redirect"]
    resume_path: str
    installation_id: str | None
    setup_action: str | None
    code: str | None
    state_raw: str | None
    github_error: str | None
    github_error_description: str | None
    flow: FlowKind | None = None
    authorize_state: GitHubAuthorizeState | None = None


class FinishResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    redirect_kind: Literal["team_setup", "personal_finish", "oauth_url", "team_oauth_success"]
    next_url: str | None = None
    team_id: int | None = None
    connect_from: str | None = None
    installation_id: str | None = None
    integration_id: str | None = None
    oauth_url: str | None = None
    error: str | None = None
    error_message: str | None = None
    pending: bool = False


def github_oauth_redirect_uri() -> str:
    return f"{settings.SITE_URL.rstrip('/')}/complete/github-link/"


def github_app_install_url(state: str) -> str:
    instance_settings = get_instance_settings(["GITHUB_APP_SLUG"])
    app_slug = instance_settings.get("GITHUB_APP_SLUG")
    if not app_slug:
        raise ApiValidationError("GitHub App is not configured on this instance (missing GITHUB_APP_SLUG).")
    return f"https://github.com/apps/{app_slug}/installations/new?{urlencode({'state': state})}"


def github_oauth_authorize_url(state: str) -> str:
    if not settings.GITHUB_APP_CLIENT_ID:
        raise ApiValidationError("GitHub App client ID is not configured (GITHUB_APP_CLIENT_ID missing).")
    return "https://github.com/login/oauth/authorize?" + urlencode(
        {"client_id": settings.GITHUB_APP_CLIENT_ID, "redirect_uri": github_oauth_redirect_uri(), "state": state}
    )


def is_valid_github_installation_id(installation_id: object | None) -> bool:
    if installation_id is None:
        return False
    return bool(GITHUB_INSTALLATION_ID_PATTERN.fullmatch(str(installation_id)))
