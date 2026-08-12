from django.db import migrations

DELETE_DUPLICATE_REPORTS_SQL = """
-- migration-analyzer: safe reason=ai observability evaluation reports are limited-use; DELETE only removes duplicate configs after runs are rewired
WITH ranked_reports AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY evaluation_id
            ORDER BY deleted ASC, enabled DESC, created_at DESC NULLS LAST, id DESC
        ) AS row_number
    FROM llm_analytics_evaluationreport
)
DELETE FROM llm_analytics_evaluationreport AS report
USING ranked_reports
WHERE ranked_reports.row_number > 1
  AND report.id = ranked_reports.id;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0018_deduplicate_evaluation_reports"),
    ]

    operations = [
        migrations.RunSQL(DELETE_DUPLICATE_REPORTS_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
