import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import Resolver404, resolve

import orjson
import structlog

logger = structlog.get_logger(__name__)

METADATA_ONLY_SCOPE = "data_access:metadata_only"
METADATA_ONLY_REQUEST_ATTR = "posthog_data_access_metadata_only"


STANDARD_ACTIONS = frozenset({"list", "retrieve", "create", "update", "partial_update", "destroy", "options"})


@dataclass(frozen=True)
class ObjectPolicy:
    allowed: bool = True
    allowed_custom_actions: frozenset[str] = frozenset()
    blocked_standard_actions: frozenset[str] = frozenset()
    redact_keys: frozenset[str] = frozenset()

    def allows(self, action: str | None) -> bool:
        if not self.allowed or action is None:
            return False
        if action in STANDARD_ACTIONS:
            return action not in self.blocked_standard_actions
        return action in self.allowed_custom_actions


def _policy(
    *, custom_actions: Iterable[str] = (), block: Iterable[str] = (), redact: Iterable[str] = ()
) -> ObjectPolicy:
    return ObjectPolicy(
        allowed_custom_actions=frozenset(custom_actions),
        blocked_standard_actions=frozenset(block),
        redact_keys=frozenset(redact),
    )


_BLOCKED = ObjectPolicy(allowed=False)

_INSIGHT_RESULT_KEYS = ("result", "hasMore", "query_status", "next_allowed_client_refresh", "is_cached")
_DEFINITION_USAGE_KEYS = ("volume_30_day", "query_usage_30_day", "last_seen_at", "example", "media_preview_urls")

SCOPE_OBJECT_POLICIES: dict[str, ObjectPolicy] = {
    "person": _BLOCKED,
    "group": _BLOCKED,
    "session_recording": _BLOCKED,
    "logs": _BLOCKED,
    "error_tracking": _BLOCKED,
    "heatmap": _BLOCKED,
    "element": _BLOCKED,
    "llm_analytics": _BLOCKED,
    "live_debugger": _BLOCKED,
    "ingestion_warning": _BLOCKED,
    "export": _BLOCKED,
    "query": _policy(custom_actions=("create_with_kind",), block=("list", "retrieve", "destroy")),
    "action": _policy(),
    "annotation": _policy(),
    "cohort": _policy(redact=("count", "errors_calculating")),
    "dashboard": _policy(custom_actions=("add_insight", "move_tile", "copy_tile"), redact=_INSIGHT_RESULT_KEYS),
    "dashboard_template": _policy(),
    "early_access_feature": _policy(),
    "event_definition": _policy(
        custom_actions=("by_name", "bulk_update_tags", "bulk_update_verified"), redact=_DEFINITION_USAGE_KEYS
    ),
    "property_definition": _policy(redact=_DEFINITION_USAGE_KEYS),
    "experiment": _policy(
        custom_actions=("launch", "pause", "resume", "end", "archive", "duplicate", "ship_variant", "reset"),
        redact=_INSIGHT_RESULT_KEYS,
    ),
    "experiment_saved_metric": _policy(),
    "experiment_holdout": _policy(),
    "feature_flag": _policy(redact=("rollout_percentage_estimate", "usage_dashboard_stats", "last_called_at")),
    "hog_function": _policy(),
    "hog_flow": _policy(),
    "batch_export": _policy(custom_actions=("pause", "unpause")),
    "insight": _policy(custom_actions=("bulk_update_tags",), redact=_INSIGHT_RESULT_KEYS),
    "insight_variable": _policy(),
    "notebook": _policy(),
    "project": _policy(custom_actions=("invoke_tool",)),
    "organization": _policy(),
    "organization_member": _policy(),
    "user": _policy(),
    "survey": _policy(redact=("responses_count", "response_count", "stats", "feature_flag_keys_usage")),
    "alert": _policy(redact=("checks", "calculated_value", "last_value")),
    "activity_log": _policy(),
    "comment": _policy(),
    "sharing_configuration": _policy(redact=("access_token", "share_passwords")),
    "product_tour": _policy(),
    "file_system": _policy(),
    "file_system_shortcut": _policy(),
    "integration": _policy(redact=("sensitive_config", "access_token", "refresh_token")),
}

BLOCKED_VIEW_CLASSES: frozenset[str] = frozenset(
    {
        "BatchExportRunViewSet",
        "BatchExportBackfillViewSet",
        "FileDownloadBatchExportOnDemandViewSet",
        "WorkflowPeopleImportViewSet",
        "ObjectMediaPreviewViewSet",
        "FeatureFlagRequestUsageViewSet",
        "TransactionalEmailLogViewSet",
        "WorkflowEmailLogViewSet",
        "MessagingEmailsViewSet",
        "KeyScopedMessagingEmailsViewSet",
        "PushTokenImportViewSet",
        "UserPushTokenViewSet",
        "InsightExplanationViewSet",
        "MCPAuditEventViewSet",
        "DesktopFeedbackViewSet",
        "AnomalyViewSet",
        "FlagValueViewSet",
        "ChangeFeedViewSet",
    }
)

ALLOWED_NON_SCOPED_URL_NAMES: frozenset[str] = frozenset({"personal_api_keys-detail"})


@dataclass(frozen=True)
class Decision:
    allowed: bool
    redact_keys: frozenset[str] = frozenset()
    reason: str = ""


def _resolve_view(request: HttpRequest) -> tuple[str | None, str | None, str | None, str | None]:
    try:
        match = resolve(request.path_info)
    except Resolver404:
        return None, None, None, None
    view_class = getattr(match.func, "cls", None) or getattr(match.func, "view_class", None)
    scope_object = getattr(view_class, "scope_object", None) if view_class is not None else None
    actions = getattr(match.func, "actions", None) or {}
    action = actions.get(request.method.lower()) if request.method else None
    if action is None and request.method == "OPTIONS":
        action = "options"
    return scope_object, action, match.url_name, getattr(view_class, "__name__", None)


def decide(request: HttpRequest) -> Decision:
    if not request.path_info.startswith("/api/"):
        return Decision(allowed=False, reason="Only the API is available to metadata-only tokens.")
    scope_object, action, url_name, view_name = _resolve_view(request)
    if url_name in ALLOWED_NON_SCOPED_URL_NAMES:
        return Decision(allowed=True)
    if scope_object is None or scope_object == "INTERNAL":
        return Decision(allowed=False, reason=f"Route {url_name or request.path_info} has no data access policy.")
    if view_name in BLOCKED_VIEW_CLASSES:
        return Decision(allowed=False, reason=f"{view_name} returns project data.")
    policy = SCOPE_OBJECT_POLICIES.get(scope_object)
    if policy is None:
        return Decision(allowed=False, reason=f"Scope object {scope_object} has no data access policy.")
    if not policy.allows(action):
        return Decision(allowed=False, reason=f"{scope_object}.{action} is not on the metadata-only allowlist.")
    return Decision(allowed=True, redact_keys=policy.redact_keys)


def redact(value: Any, keys: frozenset[str]) -> Any:
    if isinstance(value, dict):
        return {key: redact(item, keys) for key, item in value.items() if key not in keys}
    if isinstance(value, list):
        return [redact(item, keys) for item in value]
    return value


def compile_query_without_running(team: Any, query: Any) -> tuple[int, dict[str, Any]]:
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.errors import ExposedHogQLError
    from posthog.hogql.modifiers import create_default_modifiers_for_team
    from posthog.hogql.printer.utils import prepare_and_print_ast, to_printed_hogql
    from posthog.hogql.visitor import clone_expr

    from posthog.hogql_queries.query_runner import get_query_runner

    try:
        runner = get_query_runner(query, team)
        query_ast = runner.to_query()
        printed = to_printed_hogql(query_ast, team)
        prepare_and_print_ast(
            clone_expr(query_ast),
            context=HogQLContext(
                team_id=team.pk,
                enable_select_queries=True,
                modifiers=create_default_modifiers_for_team(team),
            ),
            dialect="clickhouse",
        )
    except ExposedHogQLError as error:
        return 400, {"type": "validation_error", "code": "invalid_query", "detail": str(error)}
    except NotImplementedError:
        return 400, {
            "type": "validation_error",
            "code": "not_compilable",
            "detail": "This query kind cannot run in metadata-only mode.",
        }
    except Exception as error:
        logger.info("data_access_policy_compile_failed", error_type=type(error).__name__)
        return 400, {"type": "validation_error", "code": "invalid_query", "detail": "The query could not be compiled."}
    return 200, {
        "results": [],
        "columns": [],
        "metadata_only": True,
        "valid": True,
        "hogql": printed,
        "detail": "The query is valid. PostHog did not run it for you. The user sees the result in their browser.",
    }


TAXONOMY_VALUE_KINDS = frozenset({"entity_property_values", "event_property_values", "action_property_values"})


def metadata_only_mcp_tool_response(
    team: Any, tool_name: str, args: dict[str, Any]
) -> tuple[int, dict[str, Any]] | None:
    if tool_name == "read_taxonomy":
        query = args.get("query") if isinstance(args.get("query"), dict) else {}
        if query.get("kind") not in TAXONOMY_VALUE_KINDS:
            return None
        return 403, {
            "success": False,
            "content": "Property values are project data, so they are not available in metadata-only mode. Ask the user for the value.",
        }
    if tool_name == "execute_sql":
        status, compiled = compile_query_without_running(
            team, {"kind": "HogQLQuery", "query": str(args.get("query", ""))}
        )
        if status != 200:
            return status, {"success": False, "content": compiled["detail"]}
        return 200, {
            "success": True,
            "content": "The SQL is valid. PostHog did not run it for you. The user sees the result as a table in the chat.\n"
            f"query: {json.dumps({'kind': 'HogQLQuery', 'query': args.get('query', '')})}",
        }
    return 403, {
        "success": False,
        "content": f"The {tool_name} tool returns project data, so it is not available in metadata-only mode.",
    }


def _token_scopes(request: HttpRequest) -> list[str] | None:
    from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
    from posthog.permissions import get_authenticator_scopes

    for authenticator_class in (PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication):
        authenticator = authenticator_class()
        try:
            if authenticator.authenticate(request):
                return get_authenticator_scopes(authenticator)
        except Exception:
            continue
    return None


def is_metadata_only_request(request: Any) -> bool:
    django_request = getattr(request, "_request", request)
    return bool(getattr(django_request, METADATA_ONLY_REQUEST_ATTR, False))


def _blocked(reason: str) -> JsonResponse:
    return JsonResponse(
        {
            "type": "authentication_error",
            "code": "metadata_only",
            "detail": f"Not available in metadata-only mode. {reason}",
        },
        status=403,
    )


class DataAccessPolicyMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        has_token = "HTTP_AUTHORIZATION" in request.META or "personal_api_key" in request.GET
        if not has_token or not request.path_info.startswith("/api/"):
            return self.get_response(request)
        scopes = _token_scopes(request)
        if not scopes or METADATA_ONLY_SCOPE not in scopes:
            return self.get_response(request)

        setattr(request, METADATA_ONLY_REQUEST_ATTR, True)
        decision = decide(request)
        if not decision.allowed:
            logger.info("data_access_policy_blocked", path=request.path_info, reason=decision.reason)
            return _blocked(decision.reason)

        response = self.get_response(request)
        if getattr(response, "streaming", False):
            return _blocked("Streaming responses can contain project data.")
        if response.status_code >= 500:
            return JsonResponse({"detail": "The request failed."}, status=response.status_code)
        content_type = response.get("Content-Type", "")
        if not response.content:
            return response
        if "json" not in content_type:
            return _blocked("Only JSON responses are available.")
        if not decision.redact_keys:
            return response
        try:
            payload = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            return _blocked("The response could not be checked.")
        response.content = orjson.dumps(redact(payload, decision.redact_keys))
        response["Content-Length"] = str(len(response.content))
        return response
