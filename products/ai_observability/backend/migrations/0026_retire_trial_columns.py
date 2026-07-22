from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0025_alter_evaluation_status_reason"),
    ]

    operations = [
        # Retire the trial columns from Django's state now, but keep them in the DB so pods still
        # running the previous release keep working through the rollout. Drop NOT NULL and set
        # DB-level defaults (the old model defaults) so inserts from either release stay valid:
        # new code omits the columns and gets the defaults instead of NULL, so old code never
        # reads NULL and the reverse SET NOT NULL cannot fail. A follow-up migration physically
        # drops the columns once the previous release is fully gone.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=[
                        "ALTER TABLE llm_analytics_evaluationconfig ALTER COLUMN trial_eval_limit DROP NOT NULL;",
                        "ALTER TABLE llm_analytics_evaluationconfig ALTER COLUMN trial_eval_limit SET DEFAULT 100;",
                        "ALTER TABLE llm_analytics_evaluationconfig ALTER COLUMN trial_evals_used DROP NOT NULL;",
                        "ALTER TABLE llm_analytics_evaluationconfig ALTER COLUMN trial_evals_used SET DEFAULT 0;",
                    ],
                    reverse_sql=[
                        "ALTER TABLE llm_analytics_evaluationconfig ALTER COLUMN trial_evals_used DROP DEFAULT;",
                        "ALTER TABLE llm_analytics_evaluationconfig ALTER COLUMN trial_evals_used SET NOT NULL;",
                        "ALTER TABLE llm_analytics_evaluationconfig ALTER COLUMN trial_eval_limit DROP DEFAULT;",
                        "ALTER TABLE llm_analytics_evaluationconfig ALTER COLUMN trial_eval_limit SET NOT NULL;",
                    ],
                ),
            ],
            state_operations=[
                migrations.RemoveField(model_name="evaluationconfig", name="trial_eval_limit"),
                migrations.RemoveField(model_name="evaluationconfig", name="trial_evals_used"),
            ],
        ),
    ]
