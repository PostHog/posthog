from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0023_remove_trial_evaluations"),
    ]

    operations = [
        # 0023 removed these columns from Django's model state but kept them in the DB (NOT NULL
        # dropped) so pods on the previous release kept working through the rollout. That release is
        # gone now, so drop the columns for real. This is the second phase of the retire-a-column
        # pattern. The table is low-traffic, so a plain metadata-only DROP COLUMN is fine.
        migrations.RunSQL(
            sql=[
                "ALTER TABLE llm_analytics_evaluationconfig DROP COLUMN IF EXISTS trial_eval_limit;",
                "ALTER TABLE llm_analytics_evaluationconfig DROP COLUMN IF EXISTS trial_evals_used;",
            ],
            reverse_sql=[
                "ALTER TABLE llm_analytics_evaluationconfig ADD COLUMN trial_evals_used integer;",
                "ALTER TABLE llm_analytics_evaluationconfig ADD COLUMN trial_eval_limit integer;",
            ],
        ),
    ]
