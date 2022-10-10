from typing import Dict
from posthog.models.activity_logging.activity_log import ActivityLog

def historical_exports_activity(team_id: int, plugin_config_id: int):
    entries = ActivityLog.objects.filter(
        team_id=team_id,
        scope="PluginConfig",
        item_id=plugin_config_id,
        activity__in=['job_triggered', 'export_success'],
        detail__trigger__job_type='Export historical events V2'
    )

    by_category: Dict = {
        "job_triggered": {},
        "export_success": {},
        "export_fail": {}
    }
    for entry in entries:
        by_category[entry.activity][entry.detail["trigger"]["job_id"]] = entry

    historical_exports = []
    for job_id, trigger_entry in by_category["job_triggered"].items():
        record = {
            "started_at": trigger_entry.created_at,
            "job_id": job_id,
            "payload": trigger_entry.detail["trigger"]["payload"],
        }

        if job_id in by_category["export_success"]:
            record["status"] = "success"
            record["duration"] = by_category["export_success"][job_id].created_at - trigger_entry.created_at
        elif job_id in by_category["export_fail"]:
            record["status"] = "fail"
            record["duration"] = by_category["export_fail"][job_id].created_at - trigger_entry.created_at
        else:
            record["status"] = "not_finished"
        historical_exports.append(record)

    return historical_exports

