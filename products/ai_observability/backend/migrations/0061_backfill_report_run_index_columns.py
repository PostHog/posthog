from django.db import migrations

BATCH_SIZE = 1000

# Reruns skip rows that an earlier batch filled, so an interrupted backfill resumes.
# A row without a target or status key predates that key, so it is a completed generation report.
# The report agent reads metrics only from `metadata`, so the backfill merges `content.metrics`
# into it with content winning: the oldest rows hold a mirror that predates the content key and
# can carry other keys. A mirror that is not an object is replaced, because `||` wraps a
# non-object into an array instead of merging, and the reader discards a non-object mirror.
BACKFILL_BATCH = """
    UPDATE llm_analytics_evaluationreportrun
    SET title = COALESCE(content ->> 'title', ''),
        evaluation_target = COALESCE(NULLIF(content ->> 'evaluation_target', ''), 'generation'),
        generation_status = COALESCE(NULLIF(content ->> 'generation_status', ''), 'completed'),
        metadata = CASE
            WHEN jsonb_typeof(content -> 'metrics') = 'object'
            THEN (CASE WHEN jsonb_typeof(metadata) = 'object' THEN metadata ELSE '{}'::jsonb END)
                || (content -> 'metrics')
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
        ("ai_observability", "0060_denormalize_report_run_index_columns"),
    ]

    operations = [
        # Not elidable: a squash that dropped it would add the columns without filling them,
        # and leave every existing row unreadable to the report agent.
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
