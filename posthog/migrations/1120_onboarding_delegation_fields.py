from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1117_role_external_reference"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationinvite",
            name="is_setup_delegation",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "True when this invite was created via the onboarding delegation flow. "
                    "Downstream logic routes the delegate through full onboarding on accept."
                ),
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="onboarding_skipped_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="user",
            name="onboarding_skipped_reason",
            field=models.CharField(
                max_length=32,
                null=True,
                blank=True,
                choices=[
                    ("delegated", "Delegated to teammate"),
                    ("later", "Skipped for later"),
                    ("other", "Other"),
                ],
            ),
        ),
        # db_index=False: Django's default would emit a blocking CREATE INDEX on posthog_user
        # during deploy. The index is added out-of-band in 1121 via CREATE INDEX CONCURRENTLY.
        migrations.AddField(
            model_name="user",
            name="onboarding_delegated_to_invite",
            field=models.ForeignKey(
                null=True,
                blank=True,
                db_index=False,
                on_delete=models.SET_NULL,
                related_name="delegating_users",
                to="posthog.organizationinvite",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="onboarding_delegated_to_organization_id",
            field=models.UUIDField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="user",
            name="onboarding_delegation_accepted_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
