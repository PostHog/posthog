import json
import uuid
from typing import Any, cast

from django.conf import settings
from django.http.response import HttpResponseBase

from drf_spectacular.utils import OpenApiResponse, extend_schema_field
from rest_framework import exceptions, serializers, viewsets

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.query import required_scopes_for_query_payload
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.streaming import streaming_response
from posthog.api.utils import action
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.facade.api import (
    MAX_QUERIES_PER_BATCH,
    DashboardNotFound,
    DashboardNotViewable,
    dashboard_v2_enabled,
    query_batch_stream,
    viewable_dashboard_id,
)
from products.dashboards.backend.facade.contracts import QueryBatchInput, QueryBatchTarget
from products.dashboards.backend.facade.enums import QueryBatchLanguage


@extend_schema_field({"type": "object", "additionalProperties": True})
class _JSONObjectField(serializers.JSONField):
    def to_internal_value(self, data: Any) -> Any:
        if not isinstance(data, dict):
            raise serializers.ValidationError("Expected a JSON object.")
        return super().to_internal_value(data)


class QueryBatchTargetSerializer(serializers.Serializer):
    refId = serializers.CharField(max_length=200, help_text="The panel's ID for this query. Not used for caching.")
    language = serializers.ChoiceField(
        choices=QueryBatchLanguage.choices,
        help_text=(
            "'insight': `query` is JSON `{query: <query node>, filters?, variables?}`, as a PostHog dashboard sends "
            "to `/query`. 'hogql': `query` is SQL that reads the time range through `{filters}`."
        ),
    )
    query = serializers.CharField(max_length=200_000, help_text="The query text, read according to `language`.")


class QueryBatchTimeSerializer(serializers.Serializer):
    # `from` is a Python keyword, so the field is declared under another name and renamed in get_fields.
    from_ = serializers.CharField(max_length=100, help_text="Start of the range: `now-7d`, `now-30m`, or ISO 8601.")
    to = serializers.CharField(max_length=100, help_text="End of the range: `now`, `now-1h`, or ISO 8601.")

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["from"] = fields.pop("from_")
        return fields


class QueryBatchQuerySerializer(serializers.Serializer):
    target = QueryBatchTargetSerializer(help_text="What to run.")
    time = QueryBatchTimeSerializer(
        help_text="The panel's time range. Relative expressions keep the cache key the same across reloads."
    )
    variables = _JSONObjectField(
        required=False,
        allow_null=True,
        help_text="SQL variable values by variable ID, as `/query` takes in `variables_override`.",
    )
    interval = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=20,
        help_text="For insight targets that have an interval: minute, hour, day, week, month, quarter or year.",
    )
    swr = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Serve a stale cached result at once and recompute it in the background for the next read.",
    )
    cacheOnly = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Answer from the cache only, stale or not. Never runs or refreshes the query.",
    )


class QueryBatchRequestSerializer(serializers.Serializer):
    queries = serializers.ListField(
        child=QueryBatchQuerySerializer(),
        allow_empty=False,
        max_length=MAX_QUERIES_PER_BATCH,
        help_text=f"The panels' queries, at most {MAX_QUERIES_PER_BATCH}.",
    )
    dashboard = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text=(
            "The dashboard these panels sit on. Its queries then run as that dashboard's tiles, under the "
            "dashboard query limits. Never read for anything else."
        ),
    )


class DashboardV2ViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Reads for `dashboard-v2` boards whose panels hold their queries inline."""

    scope_object = "query"

    def dangerously_get_required_scopes(self, request, view) -> list[str] | None:
        if getattr(view, "action", None) != "query_batch":
            return None
        queries = request.data.get("queries") if isinstance(request.data, dict) else None
        if not isinstance(queries, list):
            return None
        scopes = {"query:read"}
        for item in queries:
            target = item.get("target") if isinstance(item, dict) else None
            if isinstance(target, dict):
                scopes.update(required_scopes_for_query_payload(_scoped_node(target)) or [])
        return sorted(scopes)

    @validated_request(
        request_serializer=QueryBatchRequestSerializer,
        responses={
            200: OpenApiResponse(
                description=(
                    "An `application/x-ndjson` stream with one JSON line per query, in the order each finishes: "
                    "`{i, result: {result, cache: {key, "
                    "fetchedAt, stale, hit}, provenance?}}` or `{i, error}`, where `i` is the query's index. Blank "
                    "lines are keep-alives."
                )
            )
        },
        description=(
            "Run many panels' queries in one request and stream each result back as it is ready. Every query is "
            "read as the requesting user, keyed by its content, and cached hits come first."
        ),
    )
    @action(methods=["POST"], detail=False, required_scopes=["query:read"])
    def query_batch(self, request: ValidatedRequest, **kwargs: Any) -> HttpResponseBase:
        if request.user.is_anonymous:
            raise exceptions.NotFound()
        user = cast(User, request.user)
        if not dashboard_v2_enabled(self.team, str(user.distinct_id)):
            raise exceptions.NotFound()
        dashboard_id = request.validated_data.get("dashboard")
        if dashboard_id is not None:
            try:
                viewable_dashboard_id(
                    team_id=self.team.pk,
                    dashboard_id=dashboard_id,
                    user_access_control=UserAccessControl(user=user, team=self.team),
                )
            except DashboardNotFound:
                raise exceptions.NotFound("Dashboard not found.")
            except DashboardNotViewable:
                raise exceptions.PermissionDenied("You don't have access to this dashboard.")
        inputs = [
            QueryBatchInput(
                target=QueryBatchTarget(
                    ref_id=item["target"]["refId"],
                    language=QueryBatchLanguage(item["target"]["language"]),
                    query=item["target"]["query"],
                ),
                date_from=item["time"]["from"],
                date_to=item["time"]["to"],
                variables=item.get("variables"),
                interval=item.get("interval"),
                swr=item["swr"],
                cache_only=item["cacheOnly"],
            )
            for item in request.validated_data["queries"]
        ]
        stream = query_batch_stream(
            team=self.team,
            user=user,
            inputs=inputs,
            dashboard_id=dashboard_id,
            client_query_id=f"dashboard-v2-batch-{uuid.uuid4().hex[:12]}",
            asynchronous=settings.SERVER_GATEWAY_INTERFACE == "ASGI",
        )
        return streaming_response(
            stream,
            content_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )


def _scoped_node(target: dict[str, Any]) -> object:
    if target.get("language") == QueryBatchLanguage.HOGQL:
        return {"kind": "HogQLQuery"}
    text = target.get("query")
    if not isinstance(text, str):
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed.get("query") if isinstance(parsed, dict) else None
