from collections.abc import Mapping

from django.urls import reverse

from posthog.rate_limit import _UserBucketRateThrottle

from ..facade import api
from .trace_ids import encode_trace_id_segment


class TraceExportRateThrottle(_UserBucketRateThrottle):
    scope = "ai_trace_export"
    rate = "20/hour"


def trace_export_content_path(*, team_id: int, asset_id: int, export_context: Mapping[str, object]) -> str | None:
    trace_id = api.exported_trace_id(export_context)
    if trace_id is None:
        return None
    return reverse(
        "project_ai_observability_traces-export-content",
        kwargs={"parent_lookup_team_id": team_id, "pk": encode_trace_id_segment(trace_id), "export_id": asset_id},
    )
