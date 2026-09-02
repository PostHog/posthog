from django.db import migrations, models


class Migration(migrations.Migration):
    """Add provisioning_config, the JSONB column that replaces the per-capability columns.

    Schema only. The backfill lands in 1274, the Postgres defaults the retired columns need in
    1275, and the model-state removal in 1276, because a data migration or a RunSQL sharing a
    file with schema changes holds its locks for the whole file. Additive and defaulted, so this
    half is safe on its own and leaves the previous release untouched.
    """

    dependencies = [("posthog", "1272_user_ui_configuration")]

    operations = [
        migrations.AddField(
            model_name="oauthapplication",
            name="_provisioning_config",
            field=models.JSONField(
                blank=True,
                db_column="provisioning_config",
                db_default={},
                default=dict,
                help_text=(
                    "Provisioning capabilities and per-endpoint rate limits. Every "
                    "capability is off unless explicitly granted."
                ),
            ),
        ),
    ]
