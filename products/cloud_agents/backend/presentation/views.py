"""
DRF views for cloud_agents.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from django.http import HttpResponseBase

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.streaming import sse_streaming_response
from posthog.api.utils import action
from posthog.renderers import SafeJSONRenderer, ServerSentEventRenderer

from products.tasks.backend.facade.streams import sse_body_for_server_gateway

from ..facade import api
from ..facade.contracts import (
    InvalidInput,
    PresetCreateInput,
    PresetNotFound,
    RunCreateInput,
    RunListFilters,
    RunNotFound,
)
from .common import CloudAgentsViewSet, caller_from_request, parse_uuid
from .serializers import (
    IDEMPOTENCY_KEY_MAX_LENGTH,
    CloudAgentCatalogSerializer,
    CloudAgentEstimateQuerySerializer,
    CloudAgentEstimateSerializer,
    CloudAgentPresetCreateSerializer,
    CloudAgentPresetSerializer,
    CloudAgentPresetUpdateSerializer,
    CloudAgentRunCreateSerializer,
    CloudAgentRunEventsSerializer,
    CloudAgentRunListQuerySerializer,
    CloudAgentRunMessageResponseSerializer,
    CloudAgentRunMessageSerializer,
    CloudAgentRunSerializer,
    CloudAgentRunUsageSerializer,
    CloudAgentSettingsSerializer,
    CloudAgentSettingsUpdateSerializer,
    CloudAgentUsageQuerySerializer,
    CloudAgentUsageSummarySerializer,
)


def _preset_id(pk: str) -> UUID:
    preset_id = parse_uuid(pk)
    if preset_id is None:
        raise PresetNotFound()
    return preset_id


def _run_id(pk: str) -> UUID:
    run_id = parse_uuid(pk)
    if run_id is None:
        raise RunNotFound()
    return run_id


IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
IDEMPOTENCY_REPLAYED_HEADER = "Idempotency-Replayed"


def _idempotency_key(request: Request) -> str | None:
    key = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    if key is None:
        return None
    key = key.strip()
    if not 1 <= len(key) <= IDEMPOTENCY_KEY_MAX_LENGTH:
        raise InvalidInput(
            f"The {IDEMPOTENCY_KEY_HEADER} header must have from 1 to {IDEMPOTENCY_KEY_MAX_LENGTH} characters.",
            attr=IDEMPOTENCY_KEY_HEADER,
        )
    return key


class RunEventStreamRenderer(ServerSentEventRenderer):
    """Passes the frames of the stream through. An error response is not a stream, so it is written as JSON."""

    def render(self, data: Any, accepted_media_type: Any = None, renderer_context: Any = None) -> Any:
        if isinstance(data, (bytes, str)):
            return data
        return json.dumps(data).encode()


class CloudAgentRunViewSet(CloudAgentsViewSet):
    scope_object_read_actions = ["list", "retrieve", "events", "usage"]
    scope_object_write_actions = ["create", "messages", "cancel"]

    @validated_request(
        query_serializer=CloudAgentRunListQuerySerializer,
        summary="List runs",
        description="The runs of the project, newest first.",
        responses={200: OpenApiResponse(response=CloudAgentRunSerializer(many=True))},
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        runs = api.list_runs(self.team_id, RunListFilters(**request.validated_query_data))
        # A lazy sequence: the paginator counts it and takes one slice, like a queryset.
        page = self.paginate_queryset(runs)
        return self.get_paginated_response(CloudAgentRunSerializer(page, many=True).data)

    @validated_request(
        request_serializer=CloudAgentRunCreateSerializer,
        summary="Start a run",
        description=(
            "Starts a sandbox with a coding agent that works on the prompt in the repository. The response "
            "returns at once with a `queued` run. Read the run or stream its events "
            "to follow it. Send the same `Idempotency-Key` header again to get the same run and not a second one."
        ),
        parameters=[
            OpenApiParameter(
                name=IDEMPOTENCY_KEY_HEADER,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=False,
                description=(
                    f"A key of 1 to {IDEMPOTENCY_KEY_MAX_LENGTH} characters that is unique for this request. A "
                    "repeated request with the same key and the same body returns the first run with status "
                    "200 and the header `Idempotency-Replayed: true`. The same key with a different body gives "
                    "status 422."
                ),
            )
        ],
        responses={
            201: OpenApiResponse(response=CloudAgentRunSerializer, description="The run started."),
            200: OpenApiResponse(
                response=CloudAgentRunSerializer, description="The idempotency key replayed an earlier run."
            ),
        },
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        run, replayed = api.start_run(
            self.team_id,
            caller_from_request(request),
            RunCreateInput(**request.validated_data),
            _idempotency_key(request),
        )
        if replayed:
            return Response(CloudAgentRunSerializer(run).data, headers={IDEMPOTENCY_REPLAYED_HEADER: "true"})
        return Response(CloudAgentRunSerializer(run).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Retrieve a run", responses={200: CloudAgentRunSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        return Response(CloudAgentRunSerializer(api.get_run(self.team_id, _run_id(pk))).data)

    @validated_request(
        request_serializer=CloudAgentRunMessageSerializer,
        summary="Send a message to a run",
        description=(
            "Sends a follow-up message. An agent that is at work gets the message in its current session. "
            "An `idle` run starts a new agent session with the message and goes back to `queued`. "
            "A `done` run refuses the message with status 409 and the code `run_done`."
        ),
        responses={202: OpenApiResponse(response=CloudAgentRunMessageResponseSerializer)},
    )
    @action(methods=["POST"], detail=True)
    def messages(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        result = api.send_message(
            self.team_id, caller_from_request(request), _run_id(pk), request.validated_data["content"]
        )
        return Response(CloudAgentRunMessageResponseSerializer(result).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="Cancel a run",
        description=(
            "Asks a `queued` or `running` run to stop. The response has status 202 and the run can still be "
            "`running` for a short time. It is then `done` with the reason `cancelled`. An `idle` or `done` "
            "run has no agent to stop, so it is returned with status 200 and does not change."
        ),
        request=None,
        responses={
            202: OpenApiResponse(response=CloudAgentRunSerializer, description="The run is stopping."),
            200: OpenApiResponse(response=CloudAgentRunSerializer, description="The run has no agent to stop."),
        },
    )
    @action(methods=["POST"], detail=True)
    def cancel(self, request: Request, pk: str, **kwargs: Any) -> Response:
        run, accepted = api.cancel_run(self.team_id, caller_from_request(request), _run_id(pk))
        return Response(
            CloudAgentRunSerializer(run).data, status=status.HTTP_202_ACCEPTED if accepted else status.HTTP_200_OK
        )

    @extend_schema(
        summary="Retrieve the usage of a run",
        description="The cost of the run up to now, and each sandbox that it used.",
        responses={200: CloudAgentRunUsageSerializer},
    )
    @action(methods=["GET"], detail=True)
    def usage(self, request: Request, pk: str, **kwargs: Any) -> Response:
        return Response(CloudAgentRunUsageSerializer(api.get_run_usage(self.team_id, _run_id(pk))).data)

    @extend_schema(
        summary="Read the events of a run",
        description=(
            "By default, the response is one JSON object with the stored events of all agent sessions. "
            "To follow a live run, send `Accept: text/event-stream`. The response is then a Server-Sent Events "
            "stream of the current agent session. Its first frame is `event: run` with the ID, the status and "
            "the status reason of the run. `Last-Event-ID` and `start=latest` apply to the stream only. To resume "
            "after a disconnect, send the `id` of the last event in the `Last-Event-ID` header.\n\n"
            "**SDK consumers**: a generated fetch wrapper buffers the stream. Use the JSON default through it, "
            "and read the stream with a streaming `fetch` or an `EventSource` client."
        ),
        parameters=[
            OpenApiParameter(
                name="format",
                type=OpenApiTypes.STR,
                enum=["json"],
                location=OpenApiParameter.QUERY,
                required=False,
                description="`json` returns the stored events as one JSON object. This is the default.",
            ),
            OpenApiParameter(
                name="start",
                type=OpenApiTypes.STR,
                enum=["latest"],
                location=OpenApiParameter.QUERY,
                required=False,
                description="Applies to the stream only: `latest` skips the stored events and sends only new events.",
            ),
            OpenApiParameter(
                name="Last-Event-ID",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=False,
                description=(
                    "Applies to the stream only: the `id` of the last event that you received. The stream sends "
                    "the events after it."
                ),
            ),
        ],
        responses={
            (200, "application/json"): CloudAgentRunEventsSerializer,
            (200, "text/event-stream"): OpenApiTypes.STR,
        },
    )
    @action(methods=["GET"], detail=True, renderer_classes=[SafeJSONRenderer, RunEventStreamRenderer])
    def events(self, request: Request, pk: str, **kwargs: Any) -> HttpResponseBase:
        run_id = _run_id(pk)
        if isinstance(request.accepted_renderer, SafeJSONRenderer):
            return Response(CloudAgentRunEventsSerializer(api.get_run_events(self.team_id, run_id)).data)
        stream = api.prepare_run_event_stream(
            self.team_id,
            run_id,
            last_event_id=request.headers.get("Last-Event-ID"),
            start_latest=request.query_params.get("start") == "latest",
        )
        # Releases the request-thread DB connection before the long-lived stream begins. See
        # sse_streaming_response. The stream body is Redis and object storage only, so it never
        # re-acquires one.
        return sse_streaming_response(
            sse_body_for_server_gateway(lambda: api.run_event_stream(stream)),
            endpoint="cloud_agent_run_events",
        )


class CloudAgentsCatalogViewSet(CloudAgentsViewSet):
    """Project-level reads at `cloud_agents/catalog`, `cloud_agents/estimate` and `cloud_agents/usage`."""

    scope_object_read_actions = ["catalog", "estimate", "usage"]
    scope_object_write_actions: list[str] = []

    @extend_schema(
        summary="Retrieve the cloud agents catalog",
        description="The sizes, models and inference modes that a run can use, with the prices and the limits.",
        responses={200: CloudAgentCatalogSerializer},
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def catalog(self, request: Request, **kwargs: Any) -> Response:
        return Response(CloudAgentCatalogSerializer(api.get_catalog(self.team_id)).data)

    @validated_request(
        query_serializer=CloudAgentEstimateQuerySerializer,
        summary="Estimate the compute cost of a run",
        description="The compute cost of a sandbox of one size for a number of minutes. Model usage is not included.",
        responses={200: OpenApiResponse(response=CloudAgentEstimateSerializer)},
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def estimate(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        query = request.validated_query_data
        return Response(CloudAgentEstimateSerializer(api.estimate_cost(query["size"], query["minutes"])).data)

    @validated_request(
        query_serializer=CloudAgentUsageQuerySerializer,
        summary="Retrieve cloud agents usage",
        description="Cost and usage totals of the runs created in a date range, for each day or for each preset.",
        responses={200: OpenApiResponse(response=CloudAgentUsageSummarySerializer)},
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def usage(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        query = request.validated_query_data
        summary = api.get_usage_summary(
            self.team_id,
            date_from=query.get("date_from"),
            date_to=query.get("date_to"),
            group_by=query["group_by"],
        )
        return Response(CloudAgentUsageSummarySerializer(summary).data)


class CloudAgentPresetViewSet(CloudAgentsViewSet):
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create", "partial_update", "destroy"]

    @extend_schema(summary="List presets", responses={200: CloudAgentPresetSerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        presets = api.list_presets(self.team_id)
        page = self.paginate_queryset(presets)
        if page is not None:
            return self.get_paginated_response(CloudAgentPresetSerializer(page, many=True).data)
        return Response(CloudAgentPresetSerializer(presets, many=True).data)

    @validated_request(
        request_serializer=CloudAgentPresetCreateSerializer,
        summary="Create a preset",
        description="A preset is a named set of run defaults. A run that names a preset needs only a prompt.",
        responses={201: OpenApiResponse(response=CloudAgentPresetSerializer)},
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        preset = api.create_preset(
            self.team_id, PresetCreateInput(**request.validated_data), caller_from_request(request)
        )
        return Response(CloudAgentPresetSerializer(preset).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Retrieve a preset", responses={200: CloudAgentPresetSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        return Response(CloudAgentPresetSerializer(api.get_preset(self.team_id, _preset_id(pk))).data)

    @validated_request(
        request_serializer=CloudAgentPresetUpdateSerializer,
        summary="Update a preset",
        description="Only the fields in the request change. A null value clears a default.",
        responses={200: OpenApiResponse(response=CloudAgentPresetSerializer)},
    )
    def partial_update(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        preset = api.update_preset(self.team_id, _preset_id(pk), request.validated_data, caller_from_request(request))
        return Response(CloudAgentPresetSerializer(preset).data)

    @extend_schema(
        summary="Delete a preset",
        description="Runs that used the preset keep their configuration. The name becomes free.",
        request=None,
        responses={204: None},
    )
    def destroy(self, request: Request, pk: str, **kwargs: Any) -> Response:
        api.delete_preset(self.team_id, _preset_id(pk), caller_from_request(request))
        return Response(status=status.HTTP_204_NO_CONTENT)


class CloudAgentSettingsViewSet(CloudAgentsViewSet):
    """The settings of the project, a single object at `cloud_agents/settings`.

    The viewset is registered at `cloud_agents` and the action supplies the `settings` path segment,
    because a DRF router gives a collection URL no PATCH route.
    """

    scope_object_read_actions = ["team_settings"]
    scope_object_write_actions = ["update_team_settings"]

    # Not named `settings`: DRF views keep the API settings in that attribute.
    @extend_schema(
        summary="Retrieve cloud agent settings",
        description="The run defaults and the limits of the project.",
        responses={200: CloudAgentSettingsSerializer},
    )
    @action(methods=["GET"], detail=False, url_path="settings", pagination_class=None)
    def team_settings(self, request: Request, **kwargs: Any) -> Response:
        return Response(CloudAgentSettingsSerializer(api.get_team_settings(self.team_id)).data)

    @team_settings.mapping.patch
    @validated_request(
        request_serializer=CloudAgentSettingsUpdateSerializer,
        summary="Update cloud agent settings",
        description="Only the fields in the request change. A null value clears a default.",
        responses={200: OpenApiResponse(response=CloudAgentSettingsSerializer)},
    )
    def update_team_settings(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        changes = dict(request.validated_data)
        if "default_preset" in changes:
            changes["default_preset_id"] = changes.pop("default_preset")
        settings = api.update_team_settings(self.team_id, changes, caller_from_request(request))
        return Response(CloudAgentSettingsSerializer(settings).data)
