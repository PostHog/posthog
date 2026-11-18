import time

from django.db import migrations

BATCH_SIZE = 10_000
# Each updated row also writes to every index on the table, so pause to let replication keep up.
PAUSE_SECONDS = 0.1

# (foreign key column, content type app label, content type model). Spelled out rather than
# read from the tag registry, so later registry changes cannot change what this migration does.
FOREIGN_KEYS = (
    ("dashboard_id", "dashboards", "dashboard"),
    ("insight_id", "product_analytics", "insight"),
    ("event_definition_id", "event_definitions", "eventdefinition"),
    ("property_definition_id", "event_definitions", "propertydefinition"),
    ("action_id", "actions", "action"),
    ("feature_flag_id", "feature_flags", "featureflag"),
    ("experiment_saved_metric_id", "experiments", "experimentsavedmetric"),
    ("ticket_id", "conversations", "ticket"),
    ("account_id", "customer_analytics", "account"),
    ("endpoint_id", "endpoints", "endpoint"),
    ("replay_scanner_id", "replay_vision", "replayscanner"),
    ("project_id", "posthog", "project"),
    ("experiment_id", "experiments", "experiment"),
)

INTEGER_KEYS = (
    "dashboard_id",
    "insight_id",
    "action_id",
    "feature_flag_id",
    "experiment_saved_metric_id",
    "project_id::integer",
    "experiment_id",
)
UUID_KEYS = (
    "event_definition_id",
    "property_definition_id",
    "ticket_id",
    "account_id",
    "endpoint_id",
    "replay_scanner_id",
)


def backfill(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM posthog_taggeditem WHERE content_type_id IS NULL LIMIT 1")
        if cursor.fetchone() is None:
            return

    content_type_model = apps.get_model("contenttypes", "ContentType")
    content_type_ids = {
        column: content_type_model.objects.get_or_create(app_label=app_label, model=model)[0].id
        for column, app_label, model in FOREIGN_KEYS
    }
    content_type_case = " ".join(
        f"WHEN ti.{column} IS NOT NULL THEN {content_type_id}" for column, content_type_id in content_type_ids.items()
    )
    update_sql = f"""
        UPDATE posthog_taggeditem AS ti
        SET content_type_id = CASE {content_type_case} END,
            object_id = COALESCE({", ".join(f"ti.{key}" for key in INTEGER_KEYS)}),
            object_uuid = COALESCE({", ".join(f"ti.{key}" for key in UUID_KEYS)}),
            team_id = tag.team_id
        FROM posthog_tag AS tag
        WHERE ti.id = ANY(%s::uuid[])
          AND tag.id = ti.tag_id
          AND ti.content_type_id IS NULL
    """

    last_id = None
    updated = 0
    while True:
        with connection.cursor() as cursor:
            if last_id is None:
                cursor.execute("SELECT id FROM posthog_taggeditem ORDER BY id LIMIT %s", [BATCH_SIZE])
            else:
                cursor.execute(
                    "SELECT id FROM posthog_taggeditem WHERE id > %s ORDER BY id LIMIT %s", [last_id, BATCH_SIZE]
                )
            ids = [row[0] for row in cursor.fetchall()]
            if not ids:
                break
            cursor.execute(update_sql, [ids])
            updated += cursor.rowcount
            last_id = ids[-1]
        time.sleep(PAUSE_SECONDS)

    print(f"Backfilled the generic pointer on {updated} tagged items")  # noqa: T201


class Migration(migrations.Migration):
    # Each batch commits on its own, so a retry after a timeout only fills the rows still empty.
    atomic = False

    dependencies = [
        ("posthog", "1369_taggeditem_legacy_reverse_accessors"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
