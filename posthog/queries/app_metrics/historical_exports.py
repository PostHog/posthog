import json
from datetime import timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.plugin import PluginStorage
from posthog.models.team.team import Team
from posthog.queries.app_metrics.app_metrics import AppMetricsErrorsQuery, AppMetricsQuery
from posthog.queries.app_metrics.serializers import AppMetricsRequestSerializer


def historical_exports_activity(team_id: int, plugin_config_id: int, job_id: Optional[str] = None):
    from posthog.api.shared import UserBasicSerializer

    entries = ActivityLog.objects.filter(
        team_id=team_id,
        scope="PluginConfig",
        item_id=plugin_config_id,
        activity__in=["job_triggered", "export_success", "export_fail"],
        detail__trigger__job_type="Export historical events V2",
        **({"detail__trigger__job_id": job_id} if job_id is not None else {}),
    )

    by_category: dict = {"job_triggered": {}, "export_success": {}, "export_fail": {}}
    for entry in entries:
        by_category[entry.activity][entry.detail["trigger"]["job_id"]] = entry

    historical_exports = []
    for export_job_id, trigger_entry in by_category["job_triggered"].items():
        record = {
            "created_at": trigger_entry.created_at,
            "created_by": UserBasicSerializer(instance=trigger_entry.user).data,
            "job_id": export_job_id,
            "payload": trigger_entry.detail["trigger"]["payload"],
        }

        if export_job_id in by_category["export_success"]:
            entry = by_category["export_success"][export_job_id]
            record["status"] = "success"
            record["finished_at"] = entry.created_at
            record["duration"] = (entry.created_at - trigger_entry.created_at).total_seconds()
        elif export_job_id in by_category["export_fail"]:
            entry = by_category["export_fail"][export_job_id]
            record["status"] = "fail"
            record["finished_at"] = entry.created_at
            record["duration"] = (entry.created_at - trigger_entry.created_at).total_seconds()
            record["failure_reason"] = entry.detail["trigger"]["payload"].get("failure_reason")
        else:
            record["status"] = "not_finished"
            progress = _fetch_export_progress(plugin_config_id, export_job_id)
            if progress is not None:
                record["progress"] = progress
        historical_exports.append(record)

    historical_exports.sort(key=lambda record: record["created_at"], reverse=True)

    return historical_exports


def historical_export_metrics(team: Team, plugin_config_id: int, job_id: str):
    [export_summary] = historical_exports_activity(team_id=team.pk, plugin_config_id=plugin_config_id, job_id=job_id)

    filter_data = {
        "category": "exportEvents",
        "job_id": job_id,
        "date_from": (export_summary["created_at"] - timedelta(hours=1)).astimezone(ZoneInfo("UTC")).isoformat(),
    }
    if "finished_at" in export_summary:
        filter_data["date_to"] = (
            (export_summary["finished_at"] + timedelta(hours=1)).astimezone(ZoneInfo("UTC")).isoformat()
        )

    filter = AppMetricsRequestSerializer(data=filter_data)
    filter.is_valid(raise_exception=True)
    metric_results = AppMetricsQuery(team, plugin_config_id, filter).run()
    errors = AppMetricsErrorsQuery(team, plugin_config_id, filter).run()

    return {"summary": export_summary, "metrics": metric_results, "errors": errors}


def _fetch_export_progress(plugin_config_id: int, job_id: str) -> Optional[float]:
    coordination_entry = PluginStorage.objects.filter(
        plugin_config_id=plugin_config_id,
        # Keep this in sync with plugin-server/src/worker/vm/upgrades/historical-export/export-historical-events-v2.ts
        key="EXPORT_COORDINATION",
    ).first()

    if coordination_entry is None:
        return None

    return json.loads(coordination_entry.value).get("progress")
