"""Canvas connectors: live third-party data a canvas reads as the viewer (ph.connectors).

A connector call names a provider and a tool. The host forwards
ph.connectors.call(provider, tool, arguments) to the call endpoint, which
checks the canvas's declared capabilities and runs the tool with the
viewer's own connection, never the author's. Two provider families share
the pipeline:

- Native providers (``github``) run against the viewer's ``UserIntegration``
  through a registry of hand-written read tools, in the shape of the action
  registry.
- MCP providers (``mcp:<host>``) run against the viewer's MCP store
  installation for that host, through the store's own policy and audit.

Every tool this module exposes is read-only. Writes are a follow-up that
needs a user gesture and a confirm step in the host.
"""

import json
import base64
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from django.db import models

import structlog
import posthoganalytics
from rest_framework import serializers

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.user_integration import ReauthorizationRequired, UserGitHubIntegration, UserIntegration

from products.mcp_store.backend.facade import api as mcp_store_facade
from products.mcp_store.backend.facade.contracts import ConnectorTool as McpConnectorTool

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

# Rollout gate, evaluated per team. Fails closed: connectors stay off when the
# flag cannot be evaluated, because every call spends the viewer's credential.
CANVAS_CONNECTORS_FLAG = "canvas-connectors"

MCP_PROVIDER_PREFIX = "mcp:"
# Results cross the postMessage bridge into the sandbox; a runaway tool result
# must not be able to stall the host.
MAX_RESULT_BYTES = 256 * 1024
_GITHUB_SOURCE = "canvas_connectors"
_PERSONAL_INTEGRATIONS_PATH = "/settings/user-personal-integrations"


class ConnectorCallStatus(models.TextChoices):
    OK = "ok"
    NOT_CONNECTED = "not_connected"
    NEEDS_REAUTH = "needs_reauth"
    BLOCKED = "blocked"
    TOOL_MISSING = "tool_missing"
    WRITE_BLOCKED = "write_blocked"
    UPSTREAM_ERROR = "upstream_error"


class ConnectorKind(models.TextChoices):
    NATIVE = "native"
    MCP = "mcp"


def canvas_connectors_enabled(team: "Team") -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                CANVAS_CONNECTORS_FLAG,
                str(team.uuid),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("canvas_connectors_flag_check_failed")
        return False


class ConnectorToolError(Exception):
    """The upstream service refused or failed the tool call."""


@frozen
class ConnectorCallResult:
    status: ConnectorCallStatus
    result: dict[str, Any] | None = None
    detail: str = ""
    truncated: bool = False
    # Where the viewer connects the provider, for the not_connected state.
    connect_path: str | None = None


@frozen
class NativeConnectorTool:
    """One read tool of a native provider: what it reads, its payload shape, and its authoring docs."""

    name: str
    summary: str
    payload_serializer: type[serializers.Serializer]
    execute: Callable[[UserIntegration, dict[str, Any]], dict[str, Any]]
    usage: str
    read_only: bool = True


@frozen
class NativeConnector:
    provider: str
    label: str
    integration_kind: str
    tools: dict[str, NativeConnectorTool]


class GitHubRepositorySerializer(serializers.Serializer):
    repository = serializers.RegexField(
        r"^(?:[A-Za-z0-9._-]+/)?[A-Za-z0-9._-]+$",
        max_length=200,
        help_text="Repository as 'owner/name', or 'name' for a repository in the connection's own account.",
    )

    def validate_repository(self, value: str) -> str:
        # The regex admits dots, so a dot-only segment would traverse the API path.
        if any(segment.strip(".") == "" for segment in value.split("/")):
            raise serializers.ValidationError("Repository segments must not be only dots.")
        return value


class GitHubListPullRequestsPayloadSerializer(GitHubRepositorySerializer):
    state = serializers.ChoiceField(
        choices=["open", "closed", "all"], default="open", help_text="Which pull requests to list."
    )


class GitHubSearchIssuesPayloadSerializer(GitHubRepositorySerializer):
    query = serializers.CharField(max_length=256, help_text="Free text matched against issue titles and bodies.")
    limit = serializers.IntegerField(min_value=1, max_value=50, default=25, help_text="Maximum issues to return.")


class GitHubGetFileContentsPayloadSerializer(GitHubRepositorySerializer):
    file_path = serializers.CharField(max_length=1024, help_text="Path of the file inside the repository.")
    ref = serializers.RegexField(
        r"^[A-Za-z0-9._/-]+$",
        required=False,
        allow_null=True,
        default=None,
        max_length=256,
        help_text="Branch, tag, or commit SHA.",
    )

    def validate_file_path(self, value: str) -> str:
        segments = value.strip("/").split("/")
        if any(segment.strip(".") == "" or "?" in segment or "#" in segment for segment in segments):
            raise serializers.ValidationError("File path segments must be plain names.")
        return "/".join(segments)


def _github_client(integration: UserIntegration) -> UserGitHubIntegration:
    return UserGitHubIntegration(integration, source=_GITHUB_SOURCE)


def _github_repo_path(client: UserGitHubIntegration, repository: str) -> str:
    return repository if "/" in repository else f"{client.organization()}/{repository}"


def _github_list_pull_requests(integration: UserIntegration, payload: dict[str, Any]) -> dict[str, Any]:
    client = _github_client(integration)
    response = client.api_request(
        "GET",
        f"/repos/{_github_repo_path(client, payload['repository'])}/pulls",
        endpoint="/repos/{owner}/{repo}/pulls",
        params={"state": payload["state"], "per_page": 100},
    )
    if response.status_code != 200:
        raise ConnectorToolError(f"GitHub returned HTTP {response.status_code} for the pull request list.")
    return {
        "pull_requests": [
            {
                "number": pr["number"],
                "title": pr["title"],
                "url": pr["html_url"],
                "state": pr["state"],
                "draft": bool(pr.get("draft")),
                "author": (pr.get("user") or {}).get("login"),
                "head_branch": pr["head"]["ref"],
                "base_branch": pr["base"]["ref"],
                "created_at": pr["created_at"],
                "updated_at": pr["updated_at"],
            }
            for pr in response.json()
        ]
    }


def _github_search_issues(integration: UserIntegration, payload: dict[str, Any]) -> dict[str, Any]:
    client = _github_client(integration)
    repo_path = _github_repo_path(client, payload["repository"])
    # Quote the text so search qualifiers in it (repo:, OR) are matched, not interpreted.
    quoted = payload["query"].replace('"', " ")
    response = client.api_request(
        "GET",
        "/search/issues",
        endpoint="/search/issues",
        params={"q": f'repo:{repo_path} is:issue "{quoted}"', "per_page": payload["limit"]},
    )
    if response.status_code != 200:
        raise ConnectorToolError(f"GitHub returned HTTP {response.status_code} for the issue search.")
    return {
        "issues": [
            {
                "number": issue["number"],
                "title": issue["title"],
                "url": issue["html_url"],
                "state": issue["state"],
                "author": (issue.get("user") or {}).get("login"),
                "labels": [label.get("name") for label in issue.get("labels") or [] if isinstance(label, dict)],
                "created_at": issue["created_at"],
                "updated_at": issue["updated_at"],
            }
            for issue in response.json().get("items") or []
        ]
    }


def _github_get_file_contents(integration: UserIntegration, payload: dict[str, Any]) -> dict[str, Any]:
    client = _github_client(integration)
    repo_path = _github_repo_path(client, payload["repository"])
    ref = payload.get("ref")
    response = client.api_request(
        "GET",
        f"/repos/{repo_path}/contents/{payload['file_path']}",
        endpoint="/repos/{owner}/{repo}/contents/{path}",
        params={"ref": ref} if ref else None,
    )
    if response.status_code == 404:
        return {"file": None}
    if response.status_code != 200:
        raise ConnectorToolError(f"GitHub returned HTTP {response.status_code} for the file read.")
    body = response.json()
    if body.get("encoding") != "base64" or not isinstance(body.get("content"), str):
        raise ConnectorToolError("GitHub returned a directory or a file too large to read inline.")
    content = base64.b64decode(body["content"]).decode("utf-8", errors="replace")
    return {"file": {"content": content, "sha": body.get("sha"), "size": body.get("size")}}


NATIVE_CONNECTORS: dict[str, NativeConnector] = {
    connector.provider: connector
    for connector in [
        NativeConnector(
            provider="github",
            label="GitHub",
            integration_kind=UserIntegration.IntegrationKind.GITHUB,
            tools={
                tool.name: tool
                for tool in [
                    NativeConnectorTool(
                        name="list_pull_requests",
                        summary="List a repository's pull requests.",
                        payload_serializer=GitHubListPullRequestsPayloadSerializer,
                        execute=_github_list_pull_requests,
                        usage=(
                            "Arguments `{repository, state?}` → result `{pull_requests: [{number, title, url, state, "
                            "draft, author, head_branch, base_branch, created_at, updated_at}]}`. `state` is open "
                            "(default), closed, or all. Returns at most 100 pull requests, newest first."
                        ),
                    ),
                    NativeConnectorTool(
                        name="search_issues",
                        summary="Search a repository's issues by text.",
                        payload_serializer=GitHubSearchIssuesPayloadSerializer,
                        execute=_github_search_issues,
                        usage=(
                            "Arguments `{repository, query, limit?}` → result `{issues: [{number, title, url, state, "
                            "...}]}`. The query is matched against titles and bodies; GitHub search syntax in it "
                            "is quoted, not interpreted. `limit` defaults to 25, max 50."
                        ),
                    ),
                    NativeConnectorTool(
                        name="get_file_contents",
                        summary="Read one file from a repository.",
                        payload_serializer=GitHubGetFileContentsPayloadSerializer,
                        execute=_github_get_file_contents,
                        usage=(
                            "Arguments `{repository, file_path, ref?}` → result `{file: {content, sha} | null}`. "
                            "`content` is the decoded text; `file` is null when the path does not exist at `ref` "
                            "(the default branch when omitted)."
                        ),
                    ),
                ]
            },
        ),
    ]
}


def mcp_provider_host(provider: str) -> str | None:
    """The server host an ``mcp:<host>`` provider id names, or None for any other id."""
    if not provider.startswith(MCP_PROVIDER_PREFIX):
        return None
    host = provider[len(MCP_PROVIDER_PREFIX) :].strip().lower()
    return host or None


def is_known_provider(provider: str) -> bool:
    return provider in NATIVE_CONNECTORS or mcp_provider_host(provider) is not None


def unregistered_native_tools(provider: str, tools: list[str]) -> list[str]:
    """Tool names a manifest declares for a native provider that its registry does not have."""
    connector = NATIVE_CONNECTORS.get(provider)
    if connector is None:
        return []
    return sorted(set(tools) - set(connector.tools))


def _viewer_integration(user_id: int, connector: NativeConnector) -> UserIntegration | None:
    return (
        UserIntegration.objects.filter(user_id=user_id, kind=connector.integration_kind).order_by("created_at").first()
    )


def _bounded(result: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    serialized = json.dumps(result, default=str)
    if len(serialized.encode("utf-8")) <= MAX_RESULT_BYTES:
        return result, False
    return {"preview": serialized[: MAX_RESULT_BYTES // 2]}, True


def _call_native_tool(
    user_id: int, connector: NativeConnector, tool_name: str, arguments: dict[str, Any]
) -> ConnectorCallResult:
    tool = connector.tools.get(tool_name)
    if tool is None:
        return ConnectorCallResult(
            status=ConnectorCallStatus.TOOL_MISSING,
            detail=f'Unknown {connector.label} tool "{tool_name}". Registered tools: {", ".join(sorted(connector.tools))}.',
        )
    integration = _viewer_integration(user_id, connector)
    if integration is None:
        return ConnectorCallResult(
            status=ConnectorCallStatus.NOT_CONNECTED,
            detail=f"You have not connected {connector.label}.",
            connect_path=_PERSONAL_INTEGRATIONS_PATH,
        )
    payload = tool.payload_serializer(data=arguments)
    if not payload.is_valid():
        raise serializers.ValidationError(payload.errors)
    try:
        result = tool.execute(integration, payload.validated_data)
    except ReauthorizationRequired as error:
        return ConnectorCallResult(
            status=ConnectorCallStatus.NEEDS_REAUTH, detail=str(error), connect_path=_PERSONAL_INTEGRATIONS_PATH
        )
    except (ConnectorToolError, GitHubIntegrationError, GitHubRateLimitError, EgressBudgetExhausted) as error:
        return ConnectorCallResult(status=ConnectorCallStatus.UPSTREAM_ERROR, detail=str(error))
    bounded, truncated = _bounded(result)
    return ConnectorCallResult(status=ConnectorCallStatus.OK, result=bounded, truncated=truncated)


def _call_mcp_tool(
    team_id: int, user_id: int, host: str, tool_name: str, arguments: dict[str, Any], actor_label: str
) -> ConnectorCallResult:
    outcome = mcp_store_facade.call_member_server_tool(
        team_id, user_id, host, tool_name, arguments, actor_label=actor_label, allow_writes=False
    )
    if outcome.status != "ok":
        return ConnectorCallResult(
            status=ConnectorCallStatus(outcome.status),
            detail=outcome.detail,
            connect_path="/settings/mcp-servers" if outcome.status in ("not_connected", "needs_reauth") else None,
        )
    bounded, truncated = _bounded(
        {
            "content": list(outcome.content),
            "structured_content": outcome.structured_content,
            "is_error": outcome.is_error,
        }
    )
    return ConnectorCallResult(status=ConnectorCallStatus.OK, result=bounded, truncated=truncated)


def call_connector_tool(
    team_id: int,
    user_id: int,
    provider: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    actor_label: str = "",
) -> ConnectorCallResult:
    """Run one declared connector tool as the viewer. The caller has already
    checked the canvas's capabilities and the rollout flag."""
    connector = NATIVE_CONNECTORS.get(provider)
    if connector is not None:
        return _call_native_tool(user_id, connector, tool_name, arguments)
    host = mcp_provider_host(provider)
    if host is None:
        return ConnectorCallResult(
            status=ConnectorCallStatus.TOOL_MISSING,
            detail=f'Unknown provider "{provider}". Use a native provider ({", ".join(sorted(NATIVE_CONNECTORS))}) '
            f'or "{MCP_PROVIDER_PREFIX}<server host>".',
        )
    return _call_mcp_tool(team_id, user_id, host, tool_name, arguments, actor_label)


@frozen
class ConnectorToolListing:
    name: str
    summary: str
    read_only: bool
    input_schema: dict[str, Any]
    usage: str


@frozen
class ConnectorListing:
    provider: str
    label: str
    kind: ConnectorKind
    connected: bool
    connect_path: str
    tools: list[ConnectorToolListing]


def _native_tool_schema(tool: NativeConnectorTool) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, field in tool.payload_serializer().fields.items():
        entry: dict[str, Any] = {"type": _json_type(field), "description": str(field.help_text or "")}
        if isinstance(field, serializers.ChoiceField):
            entry["enum"] = list(field.choices)
        properties[name] = entry
        if field.required:
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


def _json_type(field: serializers.Field) -> str:
    if isinstance(field, serializers.IntegerField):
        return "integer"
    if isinstance(field, serializers.BooleanField):
        return "boolean"
    return "string"


def _mcp_tool_listing(tool: McpConnectorTool) -> ConnectorToolListing:
    return ConnectorToolListing(
        name=tool.name,
        summary=tool.description.split("\n", 1)[0][:200],
        read_only=tool.read_only,
        input_schema=tool.input_schema,
        usage=tool.description,
    )


def connector_listings(team_id: int, user_id: int, mcp_hosts: list[str] | None = None) -> list[ConnectorListing]:
    """Every native provider, plus each requested MCP host (default: every host the
    viewer has connected), with the viewer's connection state."""
    if mcp_hosts is None:
        mcp_hosts = mcp_store_facade.member_server_hosts(team_id, user_id)
    listings = [
        ConnectorListing(
            provider=connector.provider,
            label=connector.label,
            kind=ConnectorKind.NATIVE,
            connected=_viewer_integration(user_id, connector) is not None,
            connect_path=_PERSONAL_INTEGRATIONS_PATH,
            tools=[
                ConnectorToolListing(
                    name=tool.name,
                    summary=tool.summary,
                    read_only=tool.read_only,
                    input_schema=_native_tool_schema(tool),
                    usage=tool.usage,
                )
                for tool in sorted(connector.tools.values(), key=lambda tool: tool.name)
            ],
        )
        for connector in sorted(NATIVE_CONNECTORS.values(), key=lambda connector: connector.provider)
    ]
    for host in sorted({host.lower() for host in mcp_hosts}):
        tools = mcp_store_facade.member_server_tools(team_id, user_id, host)
        listings.append(
            ConnectorListing(
                provider=f"{MCP_PROVIDER_PREFIX}{host}",
                label=host,
                kind=ConnectorKind.MCP,
                connected=tools is not None,
                connect_path="/settings/mcp-servers",
                tools=[_mcp_tool_listing(tool) for tool in tools or []],
            )
        )
    return listings
