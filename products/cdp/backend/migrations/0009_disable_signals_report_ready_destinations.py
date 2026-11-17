from collections import defaultdict

from django.db import migrations, transaction

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 1000
REPORT_READY_EVENT = "$signals_report_ready"


def disable_report_ready_destinations(apps, schema_editor):
    """Disable destinations that subscribed to `$signals_report_ready` before the API checked Inbox read access.

    Their owners turn them back on through the API, which now requires that access. The event is new and its
    flag is off, so no row is expected to match.
    """
    HogFunction = apps.get_model("cdp", "HogFunction")
    db_alias = schema_editor.connection.alias

    # `type` and `enabled` lead the (type, enabled, team) index, so only enabled internal destinations are scanned.
    matching = (
        HogFunction.objects.using(db_alias)
        # Soft-deleted rows too: a restore must not bring back a destination that never passed the read check.
        .filter(type="internal_destination", enabled=True)
        .filter(filters__events__contains=[{"id": REPORT_READY_EVENT}])
    )
    disabled_by_team: dict[int, list[str]] = defaultdict(list)
    while True:
        batch = list(matching.order_by("pk").values_list("pk", "team_id")[:BATCH_SIZE])
        if not batch:
            break
        HogFunction.objects.using(db_alias).filter(pk__in=[pk for pk, _ in batch]).update(enabled=False)
        for pk, team_id in batch:
            disabled_by_team[team_id].append(str(pk))

    disabled = sum(len(ids) for ids in disabled_by_team.values())
    logger.info("disabled_signals_report_ready_destinations", disabled_rows=disabled, teams=len(disabled_by_team))

    if not disabled_by_team:
        return
    from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers  # noqa: PLC0415

    def reload_disabled() -> None:
        for team_id, hog_function_ids in disabled_by_team.items():
            try:
                reload_hog_functions_on_workers(team_id=team_id, hog_function_ids=hog_function_ids)
            except Exception:
                # The workers also refresh on their own schedule, so a missed reload only delays the stop.
                logger.exception("signals_report_ready_destination_reload_failed", team_id=team_id)

    # A worker that reloads before the migration commits reads the old enabled state and caches it.
    transaction.on_commit(reload_disabled, using=db_alias)


class Migration(migrations.Migration):
    dependencies = [
        ("cdp", "0008_squash_2026_11_02_schema_addons"),
    ]

    operations = [
        migrations.RunPython(disable_report_ready_destinations, migrations.RunPython.noop, elidable=True),
    ]
