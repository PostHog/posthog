import json
from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def mark_inactive_exports_as_finished(apps, _):
    migration_start_time = timezone.now()

    ActivityLog = apps.get_model("posthog", "ActivityLog")
    PluginStorage = apps.get_model("posthog", "PluginStorage")
    entries = ActivityLog.objects.filter(
        scope="PluginConfig",
        activity__in=["job_triggered", "export_success", "export_fail"],
        detail__trigger__job_type="Export historical events V2",
    )

    def key(entry):
        return (entry.team_id, entry.item_id, entry.detail["trigger"]["job_id"])

    def should_verify_if_ongoing(start_entry, finished_exports):
        # Either it isn't finished or it has been started in the last 5 minutes - might not yet be picked up.
        return key(start_entry) not in finished_exports and migration_start_time - start_entry.created_at > timedelta(
            minutes=5
        )

    start_entries, finished_exports = [], set()
    for entry in entries:
        if entry.activity == "job_triggered":
            start_entries.append(entry)
        else:
            finished_exports.add(key(entry))

    start_entries = list(
        filter(
            lambda entry: should_verify_if_ongoing(entry, finished_exports),
            start_entries,
        )
    )

    for entry in start_entries:
        expected_running_job_id = entry.detail["trigger"]["job_id"]
        storage_entry = PluginStorage.objects.filter(
            plugin_config_id=entry.item_id,
            # Keep this in sync with plugin-server/src/worker/vm/upgrades/historical-export/export-historical-events-v2.ts
            key="EXPORT_PARAMETERS",
        ).first()

        if storage_entry is None or json.loads(storage_entry.value).get("id") != expected_running_job_id:
            ActivityLog.objects.create(
                team_id=entry.team_id,
                organization_id=entry.organization_id,
                scope="PluginConfig",
                item_id=entry.item_id,
                is_system=True,
                activity="export_fail",
                detail={
                    **entry.detail,
                    "trigger": {
                        **entry.detail["trigger"],
                        "failure_reason": "Export was killed after too much inactivity",
                    },
                },
            )


# Because of the nature of this migration, there's no way to reverse it without potentially destroying customer data
# However, we still need a reverse function, so that we can rollback other migrations
def reverse(apps, _):
    pass


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0272_alter_organization_plugins_access_level"),
    ]

    operations = [migrations.RunPython(mark_inactive_exports_as_finished, reverse, elidable=True)]
