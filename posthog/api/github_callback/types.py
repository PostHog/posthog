"""Shared types and constants for GitHub setup callbacks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from urllib.parse import parse_qsl, urlparse

from django.conf import settings

GITHUB_INSTALL_STATE_CACHE_PREFIX = "github_user_install_state:"
GITHUB_INSTALL_STATE_TTL_SECONDS = 10 * 60
GITHUB_AUTHORIZE_STATE_CACHE_TTL_SECONDS = 60 * 5
GITHUB_UNIFIED_AUTHORIZE_CACHE_PREFIX = "github_authorize:"
GITHUB_UNIFIED_AUTHORIZE_PENDING_PREFIX = "github_authorize_pending:"

ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH = "/account-connected/github-integration"
PERSONAL_INTEGRATIONS_SETTINGS_PATH = "/settings/user-personal-integrations"
MOBILE_GITHUB_CALLBACK_URL = "posthog://github/callback"
APP_CONNECT_FROM_VALUES = ("posthog_code", "posthog_mobile")

CallbackEntry = Literal["setup_url", "oauth_redirect"]


class FlowKind(StrEnum):
    TEAM_INSTALL = "team_install"
    TEAM_UPDATE = "team_update"
    TEAM_OAUTH = "team_oauth"
    PERSONAL_INSTALL = "personal_install"
    PERSONAL_OAUTH = "personal_oauth"
    PERSONAL_UPDATE = "personal_update"
    OAUTH_DISCOVER = "oauth_discover"


@dataclass(frozen=True)
class GitHubAuthorizeState:
    token: str
    flow: FlowKind
    user_id: int
    team_id: int | None = None
    installation_id: str | None = None
    next_url: str | None = None
    connect_from: str | None = None


@dataclass
class CallbackContext:
    entry: CallbackEntry
    resume_path: str
    installation_id: str | None
    setup_action: str | None
    code: str | None
    state_raw: str | None
    github_error: str | None
    github_error_description: str | None
    flow: FlowKind | None = None
    authorize_state: GitHubAuthorizeState | None = None


@dataclass(frozen=True)
class FinishResult:
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


def connect_from_for_next(next_url: str) -> str | None:
    connect_from = dict(parse_qsl(urlparse(next_url).query)).get("connect_from")
    return connect_from if connect_from == "posthog_code" else None


def github_oauth_redirect_uri() -> str:
    return f"{settings.SITE_URL.rstrip('/')}/complete/github-link/"


def github_team_integration_setup_callback_uri() -> str:
    return f"{settings.SITE_URL.rstrip('/')}/integrations/github/callback"


def github_integrations_settings_path(team_id: int) -> str:
    return f"/project/{team_id}/settings/project-integrations"


def github_oauth_callback_error_code(github_error: str) -> str:
    return "access_denied" if github_error == "access_denied" else "github_oauth_error"
