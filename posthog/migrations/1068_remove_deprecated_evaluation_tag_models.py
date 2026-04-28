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
                # Constraint names are Django's auto-generated truncated names with
                # CRC32 hash suffixes (found via pg_constraint catalog).
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE IF EXISTS posthog_featureflagevaluationtag "
                        "DROP CONSTRAINT IF EXISTS posthog_featureflage_feature_flag_id_bb76119f_fk_posthog_f;"
                        "ALTER TABLE IF EXISTS posthog_featureflagevaluationtag "
                        "DROP CONSTRAINT IF EXISTS posthog_featureflage_tag_id_fe214962_fk_posthog_t;"
                        "ALTER TABLE IF EXISTS posthog_teamdefaultevaluationtag "
                        "DROP CONSTRAINT IF EXISTS posthog_teamdefaulte_team_id_35acacc0_fk_posthog_t;"
                        "ALTER TABLE IF EXISTS posthog_teamdefaultevaluationtag "
                        "DROP CONSTRAINT IF EXISTS posthog_teamdefaulte_tag_id_8d3cc3e0_fk_posthog_t;"
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
