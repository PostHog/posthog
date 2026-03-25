from django.db import migrations


class Migration(migrations.Migration):
    """
    Remove deprecated FeatureFlagEvaluationTag and TeamDefaultEvaluationTag models.

    These models were replaced by EvaluationContext, FeatureFlagEvaluationContext, and
    TeamDefaultEvaluationContext in migration 1045/1046. All application code now uses
    the new models. This migration removes the old models from Django's state and drops
    their FK constraints (to avoid blocking TRUNCATE in tests), but leaves the tables
    in the database for safety. The tables can be dropped in a follow-up migration
    after this has baked.
    """

    dependencies = [
        ("posthog", "1067_add_dashboardtemplate_is_featured"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="FeatureFlagEvaluationTag"),
                migrations.DeleteModel(name="TeamDefaultEvaluationTag"),
            ],
            database_operations=[
                # Drop FK constraints so TransactionTestCase TRUNCATE doesn't fail
                # on the orphaned tables referencing User/Team/FeatureFlag/Tag.
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE IF EXISTS posthog_featureflagevaluationtag "
                        "DROP CONSTRAINT IF EXISTS posthog_featureflagevaluationtag_feature_flag_id_fkey;"
                        "ALTER TABLE IF EXISTS posthog_featureflagevaluationtag "
                        "DROP CONSTRAINT IF EXISTS posthog_featureflagevaluationtag_tag_id_fkey;"
                        "ALTER TABLE IF EXISTS posthog_teamdefaultevaluationtag "
                        "DROP CONSTRAINT IF EXISTS posthog_teamdefaultevaluationtag_team_id_fkey;"
                        "ALTER TABLE IF EXISTS posthog_teamdefaultevaluationtag "
                        "DROP CONSTRAINT IF EXISTS posthog_teamdefaultevaluationtag_tag_id_fkey;"
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
