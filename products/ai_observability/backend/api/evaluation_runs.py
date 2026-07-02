import time
import asyncio
from datetime import timedelta

from django.conf import settings

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client import query_with_columns
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.event_usage import report_user_action
from posthog.hogql_queries.ai.ai_table_resolver import AIEventsExpiredError, AIEventsNotFoundError
from posthog.hogql_queries.ai.utils import HEAVY_COLUMN_NAMES, HEAVY_COLUMN_TO_PROPERTY, merge_heavy_properties
from posthog.permissions import AccessControlPermission
from posthog.temporal.ai_observability.run_evaluation import RunEvaluationInputs
from posthog.temporal.common.client import sync_connect

from products.ai_observability.backend.api.metrics import llma_track_latency

from ..models.evaluations import Evaluation

logger = structlog.get_logger(__name__)

EVALUATION_WORKFLOW_PREFIXES = {
    "hog": "llma-hog-eval",
    "llm_judge": "llma-llm-eval",
    "sentiment": "llma-sentiment-eval",
}


def _evaluation_workflow_prefix(evaluation_type: str) -> str:
    try:
        return EVALUATION_WORKFLOW_PREFIXES[evaluation_type]
    except KeyError:
        raise ValueError(f"Unsupported evaluation type for workflow prefix: {evaluation_type}") from None


class EvaluationRunRequestSerializer(serializers.Serializer):
    evaluation_id = serializers.UUIDField(required=True, help_text="UUID of the evaluation to run.")
    target_event_id = serializers.UUIDField(required=True, help_text="UUID of the $ai_generation event to evaluate.")
    timestamp = serializers.DateTimeField(
        required=True, help_text="ISO 8601 timestamp of the target event (needed for efficient ClickHouse lookup)."
    )
    event = serializers.CharField(
        required=False, default="$ai_generation", help_text="Event name. Defaults to '$ai_generation'."
    )
    distinct_id = serializers.CharField(
        required=False, allow_null=True, help_text="Distinct ID of the event (optional, improves lookup performance)."
    )


class EvaluationRunViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "evaluation"
    permission_classes = [IsAuthenticated, AccessControlPermission]

    @extend_schema(request=EvaluationRunRequestSerializer, responses={200: OpenApiTypes.OBJECT})
    @llma_track_latency("llma_evaluation_runs_create")
    @monitor(feature=None, endpoint="llma_evaluation_runs_create", method="POST")
    def create(self, request: Request, **kwargs) -> Response:
        """
        Create a new evaluation run.

        This endpoint validates the request and enqueues a Temporal workflow
        to asynchronously execute the evaluation.
        """
        serializer = EvaluationRunRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)

        evaluation_id = str(serializer.validated_data["evaluation_id"])
        target_event_id = str(serializer.validated_data["target_event_id"])
        timestamp = serializer.validated_data["timestamp"]
        event = serializer.validated_data["event"]
        distinct_id = serializer.validated_data.get("distinct_id")

        # Verify evaluation exists and belongs to this team
        try:
            evaluation = Evaluation.objects.get(id=evaluation_id, team_id=self.team_id, deleted=False)
        except Evaluation.DoesNotExist:
            return Response({"error": f"Evaluation {evaluation_id} not found"}, status=404)

        # Fetch event data from ClickHouse using available keys
        where_clauses = [
            "team_id = %(team_id)s",
            "toDate(timestamp) = toDate(%(timestamp)s)",
            "event = %(event)s",
            "uuid = %(event_id)s",
        ]
        params: dict[str, object] = {
            "team_id": self.team_id,
            "event_id": target_event_id.replace("-", ""),
            "timestamp": timestamp,
            "event": event,
        }

        if distinct_id:
            where_clauses.append("distinct_id = %(distinct_id)s")
            params["distinct_id"] = distinct_id

        try:
            event_data = self._fetch_event_for_evaluation(where_clauses, params)
        except AIEventsExpiredError:
            return Response(
                {
                    "error": f"Event {target_event_id} is past the ai_events retention window and can no longer be evaluated"
                },
                status=404,
            )
        except AIEventsNotFoundError:
            return Response({"error": f"Event {target_event_id} not found"}, status=404)

        # Build workflow inputs
        inputs = RunEvaluationInputs(
            evaluation_id=evaluation_id,
            event_data=event_data,
        )

        # Generate unique workflow ID
        prefix = _evaluation_workflow_prefix(evaluation.evaluation_type)
        workflow_id = f"{prefix}-{evaluation_id}-{target_event_id}-manual-{int(time.time() * 1000)}"

        # Start Temporal workflow
        try:
            client = sync_connect()
            asyncio.run(
                client.start_workflow(
                    "run-evaluation",
                    inputs,
                    id=workflow_id,
                    task_queue=settings.LLMA_EVALS_TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                    task_timeout=timedelta(minutes=2),
                )
            )

            logger.info(
                "Started evaluation workflow",
                workflow_id=workflow_id,
                evaluation_id=evaluation_id,
                target_event_id=target_event_id,
                team_id=self.team_id,
            )

            # Track evaluation run triggered
            report_user_action(
                request.user,
                "llma evaluation run triggered",
                {
                    "evaluation_id": evaluation_id,
                    "evaluation_name": evaluation.name,
                    "evaluation_type": evaluation.evaluation_type,
                    "target_event_id": target_event_id,
                    "workflow_id": workflow_id,
                    "trigger_type": "manual",
                },
                team=self.team,
                request=self.request,
            )

            return Response(
                {
                    "workflow_id": workflow_id,
                    "status": "started",
                    "evaluation": {
                        "id": str(evaluation.id),
                        "name": evaluation.name,
                    },
                    "target_event_id": target_event_id,
                },
                status=202,
            )

        except Exception as e:
            logger.exception(
                "Failed to start evaluation workflow",
                evaluation_id=evaluation_id,
                target_event_id=target_event_id,
                error=str(e),
            )
            return Response({"error": "Failed to start evaluation"}, status=500)

    def _fetch_event_for_evaluation(self, where_clauses: list[str], params: dict[str, object]) -> dict:
        """Fetch the target event with its heavy AI columns from ai_events.

        An evaluation grades the heavy $ai_input / $ai_output, which live only on the
        dedicated ai_events table. That table has a retention TTL, so when the event is
        absent we probe the long-lived events table purely to classify the miss — a
        stripped events row can't be evaluated either way.

        Raises AIEventsExpiredError if the event is gone from ai_events but still in
        events (aged past the TTL), or AIEventsNotFoundError if it is in neither.
        """
        heavy_cols = ",\n                    ".join(HEAVY_COLUMN_NAMES)
        # Tag these direct ClickHouse reads so the manual-eval-trigger lookup is attributed
        # to AI observability in query-usage analysis alongside the rest of the product.
        with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=self.team_id):
            rows = query_with_columns(
                f"""
                SELECT
                    uuid,
                    event,
                    properties,
                    timestamp,
                    team_id,
                    distinct_id,
                    person_id,
                    {heavy_cols}
                FROM ai_events
                WHERE {" AND ".join(where_clauses)}
                LIMIT 1
                """,
                params,
                team_id=self.team_id,
            )
            if not rows:
                exists_in_events = query_with_columns(
                    f"""
                    SELECT 1
                    FROM events
                    WHERE {" AND ".join(where_clauses)}
                    LIMIT 1
                    """,
                    params,
                    team_id=self.team_id,
                )
                if exists_in_events:
                    raise AIEventsExpiredError("target event has aged past the ai_events retention window")
                raise AIEventsNotFoundError("target event not found")

        event_data = rows[0]
        # Merge heavy columns back into properties for the evaluation workflow.
        heavy_columns = {col: event_data.pop(col, "") for col in HEAVY_COLUMN_TO_PROPERTY}
        event_data["properties"] = merge_heavy_properties(event_data["properties"], heavy_columns)
        return event_data
