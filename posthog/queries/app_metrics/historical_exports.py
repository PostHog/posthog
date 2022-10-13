from datetime import timedelta
from typing import Dict, Optional

import pytz

from posthog.api.shared import UserBasicSerializer
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team
from posthog.queries.app_metrics.app_metrics import AppMetricsErrorsQuery, AppMetricsQuery
from posthog.queries.app_metrics.serializers import AppMetricsRequestSerializer


def historical_exports_activity(team_id: int, plugin_config_id: int, job_id: Optional[str] = None):
    entries = ActivityLog.objects.filter(
        team_id=team_id,
        scope="PluginConfig",
        item_id=plugin_config_id,
        activity__in=["job_triggered", "export_success", "export_fail"],
        detail__trigger__job_type="Export historical events V2",
        **({"detail__trigger__job_id": job_id} if job_id is not None else {}),
    )

    by_category: Dict = {"job_triggered": {}, "export_success": {}, "export_fail": {}}
    for entry in entries:
        by_category[entry.activity][entry.detail["trigger"]["job_id"]] = entry

    historical_exports = []
    for job_id, trigger_entry in by_category["job_triggered"].items():
        record = {
            "created_at": trigger_entry.created_at,
            "created_by": UserBasicSerializer(instance=trigger_entry.user).data,
            "job_id": job_id,
            "payload": trigger_entry.detail["trigger"]["payload"],
        }

        if job_id in by_category["export_success"]:
            entry = by_category["export_success"][job_id]
            record["status"] = "success"
            record["finished_at"] = entry.created_at
            record["duration"] = (entry.created_at - trigger_entry.created_at).total_seconds()
        elif job_id in by_category["export_fail"]:
            entry = by_category["export_fail"][job_id]
            record["status"] = "fail"
            record["finished_at"] = entry.created_at
            record["duration"] = (entry.created_at - trigger_entry.created_at).total_seconds()
        else:
            record["status"] = "not_finished"
        historical_exports.append(record)

    historical_exports.sort(key=lambda record: record["created_at"], reverse=True)

    return historical_exports


def historical_export_metrics(team: Team, plugin_config_id: int, job_id: str):
    [export_summary] = historical_exports_activity(team_id=team.pk, plugin_config_id=plugin_config_id, job_id=job_id)

    filter_data = {
        "category": "exportEvents",
        "job_id": job_id,
        "date_from": (export_summary["created_at"] - timedelta(hours=1)).astimezone(pytz.utc).isoformat(),
    }
    if "finished_at" in export_summary:
        filter_data["date_to"] = (export_summary["finished_at"] + timedelta(hours=1)).astimezone(pytz.utc).isoformat()

    filter = AppMetricsRequestSerializer(data=filter_data)
    filter.is_valid(raise_exception=True)
    metric_results = AppMetricsQuery(team, plugin_config_id, filter).run()
    errors = AppMetricsErrorsQuery(team, plugin_config_id, filter).run()

    return {"summary": export_summary, "metrics": metric_results, "errors": errors}
