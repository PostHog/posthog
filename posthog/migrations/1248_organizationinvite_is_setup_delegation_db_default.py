from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Adds a Postgres-level default to posthog_organizationinvite.is_setup_delegation.

    Migration 1136 added the column NOT NULL with only a Python-level default, so during a
    rolling deploy any INSERT from stale pods that didn't set the field failed with a
    NotNullViolation. A db_default lets those inserts succeed at the database level.
    """

    dependencies = [
        ("posthog", "1247_oauthaccesstoken_token_idx"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organizationinvite",
            name="is_setup_delegation",
            field=models.BooleanField(
                default=False,
                db_default=False,
                help_text=(
                    "True when this invite was created via the onboarding delegation flow. "
                    "Downstream logic routes the delegate through full onboarding on accept."
                ),
            ),
        ),
    ]
