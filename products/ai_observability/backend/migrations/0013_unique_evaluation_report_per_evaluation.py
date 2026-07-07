from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ai_observability", "0012_deduplicate_evaluation_reports"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_evaluation_report_per_evaluation",
                    table_name="llm_analytics_evaluationreport",
                    columns="(evaluation_id)",
                    unique=True,
                ),
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name="evaluationreport",
                    constraint=models.UniqueConstraint(
                        fields=["evaluation"],
                        name="unique_evaluation_report_per_evaluation",
                    ),
                ),
            ],
        ),
    ]
