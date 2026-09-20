from django.db import migrations

BATCH_SIZE = 1000

# Reruns skip rows the previous batch already filled, so an interrupted backfill resumes.
# Targets and statuses that predate their content keys resolve the way the readers used to
# resolve a missing key: generation, and completed.
BACKFILL_BATCH = """
    UPDATE llm_analytics_evaluationreportrun
    SET title = COALESCE(content ->> 'title', ''),
        evaluation_target = COALESCE(NULLIF(content ->> 'evaluation_target', ''), 'generation'),
        generation_status = COALESCE(NULLIF(content ->> 'generation_status', ''), 'completed'),
        metadata = CASE
            WHEN metadata = '{}'::jsonb AND jsonb_typeof(content -> 'metrics') = 'object'
            THEN content -> 'metrics'
            ELSE metadata
        END
    WHERE id IN (
        SELECT id FROM llm_analytics_evaluationreportrun
        WHERE evaluation_target = ''
        LIMIT %s
    )
"""


def backfill_report_run_index_columns(connection) -> None:
    while True:
        with connection.cursor() as cursor:
            cursor.execute(BACKFILL_BATCH, [BATCH_SIZE])
            if cursor.rowcount < BATCH_SIZE:
                return


def backfill(apps, schema_editor):
    backfill_report_run_index_columns(schema_editor.connection)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ai_observability", "0051_denormalize_report_run_index_columns"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop, elidable=True),
    ]
