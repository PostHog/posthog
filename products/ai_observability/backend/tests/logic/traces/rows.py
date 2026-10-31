import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.models import Team

from products.ai_observability.backend.logic.traces.cluster_queries import ClusterRunRow
from products.ai_observability.backend.logic.traces.evaluation_result_queries import EvaluationResultRow
from products.ai_observability.backend.logic.traces.trace_queries import FeedbackEventRow, TraceEventRow

T0 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
EVALUATION_ID = "0192f2a4-5c1e-7000-8000-000000000e01"


def make_row(**overrides: Any) -> TraceEventRow:
    fields: dict[str, Any] = {
        "uuid": "event-1",
        "event": "$ai_span",
        "timestamp": T0,
        "distinct_id": "user-1",
        "session_id": None,
        "parent_id": "trace-1",
        "span_id": None,
        "generation_id": None,
        "span_name": None,
        "trace_name": None,
        "model": None,
        "provider": None,
        "input_tokens": None,
        "output_tokens": None,
        "cache_read_input_tokens": None,
        "cache_creation_input_tokens": None,
        "total_cost_usd": None,
        "latency": None,
        "is_error": False,
        "error_is_truthy": False,
        "ingestion_source": None,
        "git_branch": None,
        "git_repo": None,
    }
    return TraceEventRow(**{**fields, **overrides})


def make_feedback_row(**overrides: Any) -> FeedbackEventRow:
    fields: dict[str, Any] = {
        "uuid": "event-1",
        "event": "$ai_metric",
        "timestamp": T0,
        "parent_id": None,
        "span_id": None,
        "generation_id": None,
        "metric_name": None,
        "metric_value_json": "",
        "feedback_text_json": "",
    }
    return FeedbackEventRow(**{**fields, **overrides})


def make_evaluation_result_row(**overrides: Any) -> EvaluationResultRow:
    fields: dict[str, Any] = {
        "uuid": "result-1",
        "timestamp": T0,
        "evaluation_id": EVALUATION_ID,
        "evaluation_name": "Answers the question",
        "target_event_id": None,
        "result": "true",
        "reasoning": "Direct answer.",
        "applicable": None,
        "evaluation_type": "llm_judge",
        "result_type": None,
        "sentiment_label": None,
        "skipped": None,
        "score": None,
        "categories": None,
        "backfill_id": None,
        "start_time": None,
    }
    return EvaluationResultRow(**{**fields, **overrides})


def make_evaluation_result_event(
    *,
    uuid: str,
    team: Team,
    timestamp: datetime,
    trace_id: str = "trace-1",
    event: str = "$ai_evaluation",
    properties: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "event": event,
        "event_uuid": uuid,
        "distinct_id": "user-1",
        "team": team,
        "timestamp": timestamp,
        "properties": {"$ai_trace_id": trace_id, "$ai_evaluation_result": True, **(properties or {})},
    }


CLUSTERING_JOB_ID = "0192f2a4-5c1e-7000-8000-0000000c1a01"


def make_cluster(
    cluster_id: int,
    trace_ids: Sequence[str],
    title: str = "Restoring archived projects",
    description: str = "Users ask to bring back a deleted project.",
) -> dict[str, object]:
    return {
        "cluster_id": cluster_id,
        "size": len(trace_ids),
        "title": title,
        "description": description,
        "traces": {
            trace_id: {
                "distance_to_centroid": 0.2,
                "rank": rank,
                "x": 0.1,
                "y": -0.3,
                "timestamp": "2026-09-01T10:00:00+00:00",
                "trace_id": trace_id,
                "generation_id": None,
            }
            for rank, trace_id in enumerate(trace_ids)
        },
        "centroid": [0.1, 0.2],
        "centroid_x": 0.1,
        "centroid_y": -0.3,
        "metrics": None,
    }


def cluster_json(*clusters: Mapping[str, object]) -> str:
    return json.dumps(list(clusters))


def make_cluster_run_row(**overrides: Any) -> ClusterRunRow:
    fields: dict[str, Any] = {
        "uuid": "run-event-1",
        "timestamp": T0 + timedelta(hours=17),
        "run_id": f"1_trace_20260902_030000_{CLUSTERING_JOB_ID}",
        "job_id": CLUSTERING_JOB_ID,
        "job_name": "Support conversations",
        "clusters": cluster_json(make_cluster(0, ["trace-1", "trace-2"])),
    }
    return ClusterRunRow(**{**fields, **overrides})


def make_cluster_run_event(
    *,
    uuid: str,
    team: Team,
    timestamp: datetime,
    clusters: Sequence[Mapping[str, object]],
    run_id: str = "1_trace_20260902_030000",
    job_id: str = "",
    job_name: str = "",
    event: str = "$ai_trace_clusters",
) -> dict[str, object]:
    return {
        "event": event,
        "event_uuid": uuid,
        "distinct_id": f"clustering_trace_{team.pk}",
        "team": team,
        "timestamp": timestamp,
        "properties": {
            "$ai_clustering_run_id": run_id,
            "$ai_clustering_level": "trace",
            "$ai_clustering_job_id": job_id,
            "$ai_clustering_job_name": job_name,
            "$ai_window_start": (timestamp - timedelta(days=7)).isoformat(),
            "$ai_window_end": timestamp.isoformat(),
            "$ai_total_items_analyzed": 2,
            "$ai_clusters": list(clusters),
        },
    }
