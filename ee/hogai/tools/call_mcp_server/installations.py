from __future__ import annotations

from django.db.models import Q

from posthog.models import Team, User

from products.mcp_store.backend.models import MCPServerInstallation, MCPServerInstallationTool
from products.mcp_store.backend.oauth import refresh_installation_token


def _is_shared_row_ready(row: dict) -> bool:
    """A shared row is only usable when the owner's credential is live.

    Personal rows always surface (the user can be prompted to reauth their
    own connection), but a teammate can't fix someone else's shared
    credential, so unready shared rows are hidden from the agent instead of
    failing at call time."""
    if row["auth_type"] != "oauth":
        return True
    sensitive = row.get("sensitive_configuration") or {}
    return bool(sensitive.get("access_token")) and not sensitive.get("needs_reauth")


def _get_installations(team: Team, user: User) -> list[dict]:
    """Return the MCP installations available to this user's agent: their
    personal installations plus team-shared ones. When the user has a
    personal installation for the same URL as a shared one, the personal
    row wins — the agent acts as the user rather than through a teammate's
    shared credential."""
    rows = [
        dict(row)
        for row in MCPServerInstallation.objects.filter(team=team, is_enabled=True)
        .filter(Q(scope="shared") | Q(user=user))
        .values(
            "id",
            "display_name",
            "url",
            "auth_type",
            "sensitive_configuration",
            "scope",
        )
    ]
    personal_urls = {row["url"] for row in rows if row["scope"] != "shared"}
    return [
        row
        for row in rows
        if row["scope"] != "shared" or (row["url"] not in personal_urls and _is_shared_row_ready(row))
    ]


def _get_cached_tools(installation_id: str) -> list[dict]:
    """Return the installation's cached tool list (rows where `removed_at IS NULL`).

    Each row is shaped to match the `tools/list` payload the MCP client would
    return, so the agent code can format it identically whether the data came
    from Postgres or from a fresh upstream call. `approval_state` rides along
    so callers don't need a second query to filter/annotate."""
    rows = MCPServerInstallationTool.objects.filter(installation_id=installation_id, removed_at__isnull=True).values(
        "tool_name", "description", "input_schema", "approval_state"
    )
    return [
        {
            "name": row["tool_name"],
            "description": row["description"] or "No description",
            "inputSchema": row["input_schema"] or {},
            "approval_state": row["approval_state"],
        }
        for row in rows
    ]


def _get_tool_approval_states(installation_id: str) -> dict[str, str]:
    """Return a {tool_name: approval_state} map for an installation.

    Rows with `removed_at` set surface as `"do_not_use"` so the agent can't
    call them even if the cached approval state was previously `approved` —
    if the tool is gone upstream, it's gone. Anything not in the map is
    treated as `needs_approval` by the caller (explicit opt-in for freshly
    discovered tools)."""
    rows = MCPServerInstallationTool.objects.filter(installation_id=installation_id).values(
        "tool_name", "approval_state", "removed_at"
    )
    return {row["tool_name"]: ("do_not_use" if row["removed_at"] else row["approval_state"]) for row in rows}


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
    # refresh_installation_token resolves template-or-installation OAuth creds itself,
    # so we don't need to pre-join anything here.
    inst_obj = MCPServerInstallation.objects.get(id=installation["id"])
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
