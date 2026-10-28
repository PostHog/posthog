from django.db import migrations, transaction

BATCH_SIZE = 1_000
RETIRED_KEYS = ["unsigned_allowed_until", "partner_since"]


def drop_retired_keys(apps, schema_editor):
    connection = schema_editor.connection
    last_id = None

    while True:
        # Each page commits on its own, so no long transaction holds row locks on OAuth apps that are in use.
        with transaction.atomic(using=connection.alias), connection.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '2s'")
            cur.execute(
                """
                SELECT id FROM posthog_oauthapplication
                WHERE %s::uuid IS NULL OR id > %s::uuid
                ORDER BY id
                LIMIT %s
                """,
                [last_id, last_id, BATCH_SIZE],
            )
            ids = [row[0] for row in cur.fetchall()]
            if not ids:
                return
            cur.execute(
                """
                UPDATE posthog_oauthapplication
                SET provisioning_config = provisioning_config - %s::text[]
                WHERE id = ANY(%s) AND provisioning_config ?| %s::text[]
                """,
                [RETIRED_KEYS, ids, RETIRED_KEYS],
            )
        last_id = ids[-1]


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("posthog", "1414_remove_filesystem_rows_for_deleted_insights")]

    operations = [migrations.RunPython(drop_retired_keys, migrations.RunPython.noop)]
