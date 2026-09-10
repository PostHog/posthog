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
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from django.core.validators import RegexValidator
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


class GitHubPagePayloadSerializer(GitHubRepositorySerializer):
    page = serializers.IntegerField(min_value=1, default=1, help_text="Page number, starting at 1.")
    per_page = serializers.IntegerField(
        min_value=1, max_value=100, default=100, help_text="Results per page, up to 100."
    )
    sort = serializers.ChoiceField(
        choices=["created", "updated"], default="created", help_text="Field used to sort results."
    )
    direction = serializers.ChoiceField(choices=["asc", "desc"], default="desc", help_text="Sort direction.")


class GitHubListPullRequestsPayloadSerializer(GitHubPagePayloadSerializer):
    state = serializers.ChoiceField(
        choices=["open", "closed", "all"], default="open", help_text="Which pull requests to list."
    )


class GitHubSearchPullRequestsPayloadSerializer(GitHubListPullRequestsPayloadSerializer):
    author = serializers.RegexField(
        r"^[A-Za-z0-9][A-Za-z0-9-]*(?:\[bot\])?$",
        max_length=100,
        required=False,
        help_text="GitHub author login, or 'me' for the connected user's GitHub identity.",
    )
    query = serializers.CharField(
        max_length=256,
        required=False,
        help_text="Literal text to search in PR titles and bodies, not search qualifiers.",
    )
    draft = serializers.BooleanField(required=False, help_text="Filter to draft or non-draft pull requests.")
    per_page = serializers.IntegerField(
        min_value=1, max_value=100, default=25, help_text="Results per page, up to 100."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if (attrs["page"] - 1) * attrs["per_page"] >= 1000:
            raise serializers.ValidationError(
                {"page": "GitHub search exposes only the first 1000 matches. Narrow the filters."}
            )
        return attrs


class GitHubPullRequestPayloadSerializer(GitHubRepositorySerializer):
    pr_number = serializers.IntegerField(min_value=1, help_text="Pull request number within the repository.")


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
        params={
            "state": payload["state"],
            "page": payload["page"],
            "per_page": payload["per_page"],
            "sort": payload["sort"],
            "direction": payload["direction"],
        },
    )
    if response.status_code != 200:
        raise ConnectorToolError(f"GitHub returned HTTP {response.status_code} for the pull request list.")
    body = response.json()
    if not isinstance(body, list):
        raise ConnectorToolError("GitHub returned an invalid pull request list.")
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
            for pr in body
        ],
        "page": payload["page"],
        "per_page": payload["per_page"],
        "has_next_page": "next" in response.links,
        "next_page": payload["page"] + 1 if "next" in response.links else None,
    }


def _github_search_pull_requests(integration: UserIntegration, payload: dict[str, Any]) -> dict[str, Any]:
    client = _github_client(integration)
    query = [f"repo:{_github_repo_path(client, payload['repository'])}", "is:pr"]
    if payload["state"] != "all":
        query.append(f"is:{payload['state']}")
    author = payload.get("author")
    if author == "me":
        author = client.github_login
        if not author:
            raise ConnectorToolError(
                "The connection has no GitHub user identity. Reconnect GitHub or specify an author."
            )
    if author:
        query.append(f"author:{author}")
    if "draft" in payload:
        query.append(f"draft:{str(payload['draft']).lower()}")
    if payload.get("query"):
        quoted = payload["query"].replace('"', " ")
        query.append(f'"{quoted}"')
    response = client.api_request(
        "GET",
        "/search/issues",
        endpoint="/search/issues",
        params={
            "q": " ".join(query),
            "page": payload["page"],
            "per_page": payload["per_page"],
            "sort": payload["sort"],
            "order": payload["direction"],
        },
    )
    if response.status_code != 200:
        raise ConnectorToolError(f"GitHub returned HTTP {response.status_code} for the pull request search.")
    body = response.json()
    if (
        not isinstance(body, dict)
        or not isinstance(body.get("items"), list)
        or not isinstance(body.get("total_count"), int)
    ):
        raise ConnectorToolError("GitHub returned an invalid pull request search.")
    has_next_page = payload["page"] * payload["per_page"] < min(body["total_count"], 1000)
    return {
        "pull_requests": [
            {
                "number": pr["number"],
                "title": pr["title"],
                "url": pr["html_url"],
                "state": pr["state"],
                "draft": bool(pr.get("draft")),
                "author": (pr.get("user") or {}).get("login"),
                "created_at": pr["created_at"],
                "updated_at": pr["updated_at"],
            }
            for pr in body["items"]
        ],
        "page": payload["page"],
        "per_page": payload["per_page"],
        "has_next_page": has_next_page,
        "next_page": payload["page"] + 1 if has_next_page else None,
        "total_count": body["total_count"],
        "incomplete_results": body.get("incomplete_results", True),
        "search_limit_reached": body["total_count"] > 1000,
    }


def _github_read_result(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("success") is not True:
        raise ConnectorToolError(result.get("error") or "GitHub could not read the pull request status.")
    return {key: value for key, value in result.items() if key != "success"}


def _github_get_pull_request_snapshot(integration: UserIntegration, payload: dict[str, Any]) -> dict[str, Any]:
    client = _github_client(integration)
    repository = _github_repo_path(client, payload["repository"])
    return _github_read_result(
        client.get_pull_request_snapshot(f"https://github.com/{repository}/pull/{payload['pr_number']}")
    )


def _github_get_pull_request_checks(integration: UserIntegration, payload: dict[str, Any]) -> dict[str, Any]:
    client = _github_client(integration)
    return _github_read_result(
        client.get_pull_request_checks(_github_repo_path(client, payload["repository"]), payload["pr_number"])
    )


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
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        raise ConnectorToolError("GitHub returned an invalid issue search result.")
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
            for issue in body["items"]
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
    content = base64.b64decode("".join(body["content"].split()), validate=True).decode("utf-8", errors="replace")
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
                            "Arguments `{repository, state?, page?, per_page?, sort?, direction?}` → result "
                            "`{pull_requests: [{number, title, url, state, draft, author, head_branch, base_branch, "
                            "created_at, updated_at}], page, per_page, has_next_page, next_page}`. "
                            "Defaults to open, page 1, 100 results, created descending. "
                            "Use search_pull_requests for author filtering; do not filter one repository page locally."
                        ),
                    ),
                    NativeConnectorTool(
                        name="search_pull_requests",
                        summary="Search a repository's pull requests with author filters and pagination.",
                        payload_serializer=GitHubSearchPullRequestsPayloadSerializer,
                        execute=_github_search_pull_requests,
                        usage=(
                            "Arguments `{repository, author?, state?, draft?, query?, page?, per_page?, sort?, direction?}` "
                            "→ result `{pull_requests: [{number, title, url, state, draft, author, created_at, updated_at}], "
                            "page, per_page, has_next_page, next_page, total_count, incomplete_results, search_limit_reached}`. "
                            "Use author: 'me' for the connected user's identity. Defaults to open, page 1, 25 results, "
                            "created descending. Follow next_page with unchanged filters and per_page. "
                            "GitHub search exposes at most 1000 matches; narrow filters when search_limit_reached. "
                            "incomplete_results means GitHub returned a partial search, not response-size truncation."
                        ),
                    ),
                    NativeConnectorTool(
                        name="get_pull_request_snapshot",
                        summary="Read a pull request's CI, review decision, and head commit.",
                        payload_serializer=GitHubPullRequestPayloadSerializer,
                        execute=_github_get_pull_request_snapshot,
                        usage=(
                            "Arguments `{repository, pr_number}` → result `{number, title, url, state, ci_status, "
                            "review_decision, mergeable, head_sha, head_branch, requested_reviewer_logins, "
                            "author_login, unresolved_threads, updated_at}`. Snapshot state can be draft or merged; "
                            "list/search retain open/closed state and a separate draft boolean. "
                            "A null review_decision is unknown, not approved. Keep the PR visible if this read fails."
                        ),
                    ),
                    NativeConnectorTool(
                        name="get_pull_request_checks",
                        summary="Read check runs and external commit statuses for a pull request.",
                        payload_serializer=GitHubPullRequestPayloadSerializer,
                        execute=_github_get_pull_request_checks,
                        usage=(
                            "Arguments `{repository, pr_number}` → result `{checks: [...]}`. "
                            "Combines all pages of check runs and external commit statuses for the current head. "
                            "An empty checks list means no checks; upstream_error means status is unavailable."
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
    serialized = json.dumps(result, default=str, ensure_ascii=True)
    if len(serialized.encode("utf-8")) <= MAX_RESULT_BYTES:
        return result, False
    preview_limit = (MAX_RESULT_BYTES - len(json.dumps({"preview": ""}))) // 2
    return {"preview": serialized[:preview_limit]}, True


def _call_native_tool(
    user_id: int, connector: NativeConnector, tool_name: str, arguments: dict[str, Any]
) -> ConnectorCallResult:
    tool = connector.tools.get(tool_name)
    if tool is None:
        return ConnectorCallResult(
            status=ConnectorCallStatus.TOOL_MISSING,
            detail=f'Unknown {connector.label} tool "{tool_name}". Registered tools: {", ".join(sorted(connector.tools))}.',
        )
    payload = tool.payload_serializer(data=arguments)
    payload.is_valid(raise_exception=True)
    integrations = UserIntegration.objects.filter(user_id=user_id, kind=connector.integration_kind).order_by(
        "-created_at"
    )
    outcome = ConnectorCallResult(
        status=ConnectorCallStatus.NOT_CONNECTED,
        detail=f"You have not connected {connector.label}.",
        connect_path=_PERSONAL_INTEGRATIONS_PATH,
    )
    for integration in integrations:
        try:
            result = tool.execute(integration, payload.validated_data)
        except ReauthorizationRequired as error:
            outcome = ConnectorCallResult(
                status=ConnectorCallStatus.NEEDS_REAUTH, detail=str(error), connect_path=_PERSONAL_INTEGRATIONS_PATH
            )
            continue
        except (GitHubRateLimitError, EgressBudgetExhausted) as error:
            return ConnectorCallResult(status=ConnectorCallStatus.UPSTREAM_ERROR, detail=str(error))
        except (ConnectorToolError, GitHubIntegrationError) as error:
            outcome = ConnectorCallResult(status=ConnectorCallStatus.UPSTREAM_ERROR, detail=str(error))
            continue
        except (ValueError, TypeError, AttributeError, KeyError):
            return ConnectorCallResult(
                status=ConnectorCallStatus.UPSTREAM_ERROR, detail="GitHub returned an invalid response."
            )
        bounded, truncated = _bounded(result)
        outcome = ConnectorCallResult(status=ConnectorCallStatus.OK, result=bounded, truncated=truncated)
        if result != {"file": None}:
            return outcome
    return outcome


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
    connected: bool | None
    connect_path: str
    tools: list[ConnectorToolListing]


def _native_tool_schema(tool: NativeConnectorTool) -> dict[str, Any]:
    return _native_field_schema(tool.payload_serializer())


def _native_field_schema(field: serializers.Field) -> dict[str, Any]:
    schema: dict[str, Any]
    if isinstance(field, serializers.Serializer):
        schema = {
            "type": "object",
            "properties": {name: _native_field_schema(child) for name, child in field.fields.items()},
            "required": [name for name, child in field.fields.items() if child.required],
        }
    elif isinstance(field, (serializers.ListField, serializers.ListSerializer)):
        assert field.child is not None
        schema = {"type": "array", "items": _native_field_schema(field.child)}
    elif isinstance(field, serializers.DictField):
        schema = {"type": "object", "additionalProperties": _native_field_schema(field.child)}
    elif isinstance(field, serializers.BooleanField):
        schema = {"type": "boolean"}
    elif isinstance(field, serializers.IntegerField):
        schema = {"type": "integer"}
    elif isinstance(field, serializers.FloatField):
        schema = {"type": "number"}
    elif isinstance(field, serializers.JSONField) or type(field) is serializers.Field:
        schema = {}
    else:
        schema = {"type": "string"}
    if isinstance(field, serializers.ChoiceField):
        schema["enum"] = list(field.choices)
        if all(isinstance(choice, bool) for choice in field.choices):
            schema["type"] = "boolean"
        elif all(isinstance(choice, int) for choice in field.choices):
            schema["type"] = "integer"
    for attribute, keyword in (
        ("min_value", "minimum"),
        ("max_value", "maximum"),
        ("min_length", "minItems" if schema.get("type") == "array" else "minLength"),
        ("max_length", "maxItems" if schema.get("type") == "array" else "maxLength"),
    ):
        value = getattr(field, attribute, None)
        if value is not None:
            schema[keyword] = value
    if isinstance(field, serializers.CharField) and not field.allow_blank:
        schema["minLength"] = max(schema.get("minLength", 0), 1)
    for validator in field.validators:
        if isinstance(validator, RegexValidator):
            regex = validator.regex
            schema["pattern"] = regex if isinstance(regex, str) else regex.pattern
    if field.allow_null:
        if "type" in schema:
            schema["type"] = [schema["type"], "null"]
        if "enum" in schema:
            schema["enum"].append(None)
    if field.default is not serializers.empty and not callable(field.default):
        schema["default"] = field.default
    if field.help_text:
        schema["description"] = str(field.help_text)
    return schema


def _mcp_tool_listing(tool: McpConnectorTool) -> ConnectorToolListing:
    return ConnectorToolListing(
        name=tool.name,
        summary=tool.description.split("\n", 1)[0][:200],
        read_only=tool.read_only,
        input_schema=tool.input_schema,
        usage=tool.description,
    )


def native_connector_listings() -> list[ConnectorListing]:
    return [
        ConnectorListing(
            provider=connector.provider,
            label=connector.label,
            kind=ConnectorKind.NATIVE,
            connected=None,
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


def connector_listings(team_id: int, user_id: int, mcp_hosts: list[str] | None = None) -> list[ConnectorListing]:
    """Native and MCP tools with the viewer's connection state."""
    if mcp_hosts is None:
        mcp_hosts = mcp_store_facade.member_server_hosts(team_id, user_id)
    listings = [
        replace(listing, connected=_viewer_integration(user_id, NATIVE_CONNECTORS[listing.provider]) is not None)
        for listing in native_connector_listings()
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
