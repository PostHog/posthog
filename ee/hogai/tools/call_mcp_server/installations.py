from __future__ import annotations

import time
from typing import TYPE_CHECKING

from posthog.models import Team, User
from posthog.models.integration import OauthIntegration

from products.mcp_store.backend.models import MCPServerInstallation
from products.mcp_store.backend.oauth import TokenRefreshError, refresh_oauth_token

if TYPE_CHECKING:
    from products.mcp_store.backend.models import SensitiveConfig


def _get_installations(team: Team, user: User) -> list[dict]:
    return list(
        MCPServerInstallation.objects.filter(team=team, user=user)  # type: ignore[arg-type]
        .select_related("server")
        .values(
            "id",
            "display_name",
            "url",
            "auth_type",
            "server__oauth_provider_kind",
            "server__oauth_metadata",
            "server__oauth_client_id",
            "sensitive_configuration",
        )
    )


def _mark_needs_reauth_sync(installation_id: str) -> None:
    try:
        inst = MCPServerInstallation.objects.get(id=installation_id)
    except MCPServerInstallation.DoesNotExist:
        return
    sensitive = inst.sensitive_configuration or {}
    sensitive["needs_reauth"] = True
    inst.sensitive_configuration = sensitive
    inst.save(update_fields=["sensitive_configuration", "updated_at"])


def _refresh_token_sync(installation: dict) -> SensitiveConfig:
    sensitive = installation.get("sensitive_configuration") or {}
    refresh_token = sensitive.get("refresh_token")
    if not refresh_token:
        raise TokenRefreshError("No refresh token available")

    kind = installation.get("server__oauth_provider_kind") or ""
    token_url: str = ""
    client_id: str = ""
    client_secret: str | None = None

    if kind:
        try:
            oauth_config = OauthIntegration.oauth_config_for_kind(kind)
            token_url = oauth_config.token_url
            client_id = oauth_config.client_id
            client_secret = oauth_config.client_secret
        except NotImplementedError:
            kind = None

    if not kind:
        metadata = installation.get("server__oauth_metadata") or {}
        token_url = metadata.get("token_endpoint", "")
        client_id = installation.get("server__oauth_client_id", "")
        client_secret = None
        if not token_url or not client_id:
            raise TokenRefreshError("Missing OAuth metadata for token refresh")

    token_data = refresh_oauth_token(
        token_url=token_url,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
    )

    updated_sensitive: SensitiveConfig = {
        "access_token": token_data["access_token"],
        "token_retrieved_at": int(time.time()),
        "refresh_token": token_data.get("refresh_token", refresh_token),
    }
    if "expires_in" in token_data:
        updated_sensitive["expires_in"] = token_data["expires_in"]
    elif "expires_in" in sensitive:
        updated_sensitive["expires_in"] = sensitive["expires_in"]

    inst_obj = MCPServerInstallation.objects.get(id=installation["id"])
    inst_obj.sensitive_configuration = updated_sensitive
    inst_obj.save(update_fields=["sensitive_configuration", "updated_at"])

    return updated_sensitive


def _build_server_headers(installations: list[dict]) -> dict[str, dict[str, str]]:
    headers: dict[str, dict[str, str]] = {}
    for inst in installations:
        url = inst["url"]
        auth_type = inst.get("auth_type", "api_key")
        sensitive = inst.get("sensitive_configuration") or {}

        if auth_type == "api_key":
            if api_key := sensitive.get("api_key"):
                headers[url] = {"Authorization": f"Bearer {api_key}"}
        elif auth_type == "oauth":
            if access_token := sensitive.get("access_token"):
                headers[url] = {"Authorization": f"Bearer {access_token}"}

    return headers
