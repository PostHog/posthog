from __future__ import annotations

from posthog.models import Team, User

from products.mcp_store.backend.models import MCPServerInstallation
from products.mcp_store.backend.oauth import refresh_installation_token


def _get_installations(team: Team, user: User) -> list[dict]:
    return list(
        MCPServerInstallation.objects.filter(team=team, user=user, is_enabled=True)  # type: ignore[arg-type]
        .select_related("server")
        .values(
            "id",
            "display_name",
            "url",
            "auth_type",
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


def _refresh_token_sync(installation: dict) -> dict:
    inst_obj = MCPServerInstallation.objects.select_related("server").get(id=installation["id"])
    return refresh_installation_token(inst_obj)


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
