"""
Activity 6 of the video segment clustering workflow:
Persisting SignalReports and SignalReportArtefacts.
"""

import json
from datetime import timedelta
from typing import Any

from django.utils import timezone as django_timezone

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering.constants import (
    DEFAULT_SEGMENT_SAMPLES_PER_CLUSTER_FOR_LABELING,
    LABELING_LLM_MODEL,
)
from posthog.temporal.ai.video_segment_clustering.data import count_distinct_persons
from posthog.temporal.ai.video_segment_clustering.models import (
    Cluster,
    ClusterLabel,
    PersistReportsActivityInputs,
    PersistReportsResult,
    ReportMatch,
)
from posthog.temporal.ai.video_segment_clustering.priority import (
    calculate_priority_score,
    calculate_task_metrics,
    parse_datetime_as_utc,
    parse_timestamp_to_seconds,
)

from products.signals.backend.models import SignalReport, SignalReportArtefact

logger = structlog.get_logger(__name__)


def _build_pipeline_metadata_for_new_cluster(
    *,
    cluster: Cluster,
    label: ClusterLabel,
    algorithm: str,
    relevant_user_count: int,
    occurrence_count: int,
    segment_sample_count: int,
) -> dict[str, Any]:
    return {
        "algorithm": algorithm,
        "cluster_size": cluster.size,
        "intra_cluster_distance_p95": cluster.intra_cluster_distance_p95,
        "is_new_cluster": True,
        "matched_report_id": None,
        "match_distance": None,
        "labeling": {
            "actionable": label.actionable,
            "model": LABELING_LLM_MODEL,
            "segment_sample_count": segment_sample_count,
            "relevant_user_count": relevant_user_count,
            "occurrence_count": occurrence_count,
        },
    }


def _build_pipeline_metadata_for_matched_cluster(
    *,
    match: ReportMatch,
    algorithm: str,
    cluster_size: int,
    intra_cluster_distance_p95: float | None,
) -> dict[str, Any]:
    return {
        "algorithm": algorithm,
        "cluster_size": cluster_size,
        "intra_cluster_distance_p95": intra_cluster_distance_p95,
        "is_new_cluster": False,
        "matched_report_id": match.report_id,
        "match_distance": match.distance,
        "labeling": None,
    }


@activity.defn
async def persist_reports_activity(inputs: PersistReportsActivityInputs) -> PersistReportsResult:
    """Persists new SignalReports and updates existing relevant ones, creating SignalReportArtefacts in the process."""
    team = await Team.objects.aget(id=inputs.team_id)

    segment_lookup = {s.document_id: s for s in inputs.segments}

    report_ids: list[str] = []
    reports_created = 0
    reports_updated = 0

    # Build cluster_to_report mapping as we create reports
    cluster_to_report: dict[int, str] = {}

    # 1. Create new SignalReports for new clusters
    for cluster in inputs.new_clusters:
        label = inputs.labels.get(cluster.cluster_id)
        if not label:
            logger.warning("No label found for new cluster, skipping", cluster_id=cluster.cluster_id)
            continue

        cluster_segments = [segment_lookup[sid] for sid in cluster.segment_ids if sid in segment_lookup]
        metrics = await calculate_task_metrics(team, cluster_segments)

        # Use total_weight for priority (based on user count via logarithmic scoring)
        total_weight = calculate_priority_score(
            relevant_user_count=metrics["relevant_user_count"],
        )

        report = await SignalReport.objects.acreate(
            team=team,
            title=label.title,
            summary=label.description,
            status=SignalReport.Status.READY,
            cluster_centroid=cluster.centroid,
            cluster_centroid_updated_at=django_timezone.now(),
            total_weight=total_weight,
            signal_count=metrics["occurrence_count"],
            relevant_user_count=metrics["relevant_user_count"],
            pipeline_metadata=_build_pipeline_metadata_for_new_cluster(
                cluster=cluster,
                label=label,
                algorithm=inputs.algorithm,
                relevant_user_count=metrics["relevant_user_count"],
                occurrence_count=metrics["occurrence_count"],
                segment_sample_count=min(len(cluster_segments), DEFAULT_SEGMENT_SAMPLES_PER_CLUSTER_FOR_LABELING),
            ),
        )

        report_ids.append(str(report.id))
        cluster_to_report[cluster.cluster_id] = str(report.id)
        reports_created += 1

        logger.info(
            "Created report from cluster",
            report_id=str(report.id),
            cluster_id=cluster.cluster_id,
            cluster_size=cluster.size,
        )

    # 2. Update existing SignalReports for matched clusters (idempotent - only count new segments)
    for match in inputs.matched_clusters:
        try:
            report = await SignalReport.objects.aget(id=match.report_id)
        except SignalReport.DoesNotExist:
            logger.warning("Matched report not found", report_id=match.report_id)
            continue

        cluster_to_report[match.cluster_id] = match.report_id

        # Find segments for this matched cluster from segment_to_cluster
        matched_segment_ids = [doc_id for doc_id, cid in inputs.segment_to_cluster.items() if cid == match.cluster_id]
        cluster_segments = [segment_lookup[sid] for sid in matched_segment_ids if sid in segment_lookup]

        # Update pipeline_metadata with latest match info
        p95 = inputs.cluster_intra_distances.get(match.cluster_id) if inputs.cluster_intra_distances else None
        report.pipeline_metadata = _build_pipeline_metadata_for_matched_cluster(
            match=match,
            algorithm=inputs.algorithm,
            cluster_size=len(cluster_segments),
            intra_cluster_distance_p95=p95,
        )

        if cluster_segments:
            # Check which segments already have artefacts for this report (idempotency)
            existing_artefacts = [
                artefact
                async for artefact in SignalReportArtefact.objects.filter(
                    report_id=match.report_id, type="video_segment"
                ).only("content")
            ]
            existing_refs: set[str] = set()
            for artefact in existing_artefacts:
                try:
                    content_bytes = (
                        bytes(artefact.content) if isinstance(artefact.content, memoryview) else artefact.content
                    )
                    content = json.loads(content_bytes.decode("utf-8"))
                    existing_refs.add(
                        f"{content.get('session_id')}:{content.get('start_time')}:{content.get('end_time')}"
                    )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

            # Filter to only NEW segments (not already linked to this report)
            new_segments = []
            existing_distinct_ids: set[str] = set()
            for artefact in existing_artefacts:
                try:
                    content_bytes = (
                        bytes(artefact.content) if isinstance(artefact.content, memoryview) else artefact.content
                    )
                    content = json.loads(content_bytes.decode("utf-8"))
                    if content.get("distinct_id"):
                        existing_distinct_ids.add(content["distinct_id"])
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

            for seg in cluster_segments:
                session_start = parse_datetime_as_utc(seg.session_start_time)
                abs_start = session_start + timedelta(seconds=parse_timestamp_to_seconds(seg.start_time))
                abs_end = session_start + timedelta(seconds=parse_timestamp_to_seconds(seg.end_time))
                ref_key = f"{seg.session_id}:{abs_start.isoformat()}:{abs_end.isoformat()}"
                if ref_key not in existing_refs:
                    new_segments.append(seg)

            if new_segments:
                # Get all distinct_ids from existing artefacts + new segments for accurate user count
                new_distinct_ids = {seg.distinct_id for seg in new_segments}
                relevant_user_count = await sync_to_async(count_distinct_persons)(
                    team, list(existing_distinct_ids | new_distinct_ids)
                )

                report.relevant_user_count = relevant_user_count
                report.signal_count = (report.signal_count or 0) + len(new_segments)

                # Update total_weight for priority scoring
                report.total_weight = calculate_priority_score(
                    relevant_user_count=report.relevant_user_count,
                )

                await report.asave()
                reports_updated += 1

                logger.info(
                    "Updated report from matched cluster",
                    report_id=str(report.id),
                    cluster_id=match.cluster_id,
                    new_segments=len(new_segments),
                    skipped_existing=len(cluster_segments) - len(new_segments),
                )
            else:
                # Still save pipeline_metadata even when no new segments
                await report.asave(update_fields=["pipeline_metadata"])
        else:
            # No cluster_segments but still save pipeline_metadata
            await report.asave(update_fields=["pipeline_metadata"])

        report_ids.append(str(report.id))

    # 3. Create SignalReportArtefact records in bulk (idempotent via ignore_conflicts)
    artefacts_to_create: list[SignalReportArtefact] = []

    for segment in inputs.segments:
        cluster_id = inputs.segment_to_cluster.get(segment.document_id)
        if cluster_id is None:
            continue

        report_id = cluster_to_report.get(cluster_id)
        if not report_id:
            continue

        session_start_time = parse_datetime_as_utc(segment.session_start_time)
        segment_start_time = session_start_time + timedelta(seconds=parse_timestamp_to_seconds(segment.start_time))
        segment_end_time = session_start_time + timedelta(seconds=parse_timestamp_to_seconds(segment.end_time))

        artefact_content = json.dumps(
            {
                "session_id": segment.session_id,
                "start_time": segment_start_time.isoformat(),
                "end_time": segment_end_time.isoformat(),
                "distinct_id": segment.distinct_id,
                "content": segment.content,
            }
        ).encode("utf-8")

        artefacts_to_create.append(
            SignalReportArtefact(
                team=team,
                report_id=report_id,
                type="video_segment",
                content=artefact_content,
            )
        )

    if artefacts_to_create:
        created_artefacts = await SignalReportArtefact.objects.abulk_create(artefacts_to_create, ignore_conflicts=True)
        artefacts_created = len(created_artefacts)
    else:
        artefacts_created = 0

    return PersistReportsResult(
        reports_created=reports_created,
        reports_updated=reports_updated,
        report_ids=report_ids,
        artefacts_created=artefacts_created,
    )
