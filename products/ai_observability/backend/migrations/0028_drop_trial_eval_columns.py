from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0027_resweep_trial_status_reasons"),
    ]

    operations = [
        # The columns left Django state in 0026 (SeparateDatabaseAndState) and the previous
        # release is fully rolled off, so the physical drop is safe. IF EXISTS keeps bin/migrate
        # retries idempotent. reverse_sql restores the exact 0026 state (nullable + DB defaults)
        # so the migration graph stays reversible for TestMigrations-based tests.
        migrations.RunSQL(
            sql=[
                "ALTER TABLE llm_analytics_evaluationconfig DROP COLUMN IF EXISTS trial_eval_limit;",
                "ALTER TABLE llm_analytics_evaluationconfig DROP COLUMN IF EXISTS trial_evals_used;",
            ],
            reverse_sql=[
                "ALTER TABLE llm_analytics_evaluationconfig ADD COLUMN IF NOT EXISTS trial_evals_used integer NULL DEFAULT 0;",
                "ALTER TABLE llm_analytics_evaluationconfig ADD COLUMN IF NOT EXISTS trial_eval_limit integer NULL DEFAULT 100;",
            ],
        ),
    ]
