from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Adds most onboarding delegation / skip state (all operations run in a single transaction).

    The FK to OrganizationInvite is added in 1137_onboarding_delegation_fk (SeparateDatabaseAndState +
    NOT VALID) so the hot posthog_user table is handled without a blocking validation scan.

    Partial index in 1138_onboarding_delegated_to_invite_index.
    """

    dependencies = [
        ("posthog", "1135_alter_userproductlist_reason"),
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
        migrations.AddField(
            model_name="user",
            name="onboarding_skipped_organization_id",
            field=models.UUIDField(null=True, blank=True),
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
