from django.db import migrations

DEDUPLICATE_REPORT_RUNS_SQL = """
-- migration-analyzer: safe reason=ai observability evaluation reports are limited-use; UPDATE only rewires runs linked to duplicate evaluation configs
WITH ranked_reports AS (
    SELECT
        id,
        FIRST_VALUE(id) OVER (
            PARTITION BY evaluation_id
            ORDER BY deleted ASC, enabled DESC, created_at DESC NULLS LAST, id DESC
        ) AS keep_id,
        ROW_NUMBER() OVER (
            PARTITION BY evaluation_id
            ORDER BY deleted ASC, enabled DESC, created_at DESC NULLS LAST, id DESC
        ) AS row_number
    FROM llm_analytics_evaluationreport
)
UPDATE llm_analytics_evaluationreportrun AS run
SET report_id = ranked_reports.keep_id
FROM ranked_reports
WHERE ranked_reports.row_number > 1
  AND run.report_id = ranked_reports.id;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0015_llmprompt_version_description"),
    ]

    operations = [
        # Preserve generated report history before enforcing the one-config-per-evaluation invariant.
        migrations.RunSQL(DEDUPLICATE_REPORT_RUNS_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
