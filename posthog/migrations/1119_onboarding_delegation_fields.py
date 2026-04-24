from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Adds onboarding delegation / skip state:
      - OrganizationInvite.is_setup_delegation — flag set by the delegate endpoint so the
        acceptance flow can route the delegate through full onboarding.
      - User.onboarding_skipped_at / _reason — when the user explicitly leaves onboarding.
      - User.onboarding_skipped_organization_id — scopes the skip state to a specific org so
        a user who skips in Org A still sees onboarding in Org B.
      - User.onboarding_delegated_to_invite — FK to the delegation invite. Uses
        SeparateDatabaseAndState with `ADD CONSTRAINT ... NOT VALID` so the FK is added
        without the ACCESS EXCLUSIVE lock a plain Django FK-creation would take on
        posthog_user (a large, hot table). With nullable FKs on a fresh deploy there are
        no existing rows to validate.
      - User.onboarding_delegated_to_organization_id — denormalized UUID for fast /@me/ reads.
      - User.onboarding_delegation_accepted_at — stamped on both delegator and delegate at accept.

    atomic=False because SeparateDatabaseAndState with RunSQL for NOT VALID cannot run inside
    Django's default transaction. The associated index on onboarding_delegated_to_invite_id is
    built out-of-band (CONCURRENTLY) in 1120_onboarding_delegated_to_invite_index.py.
    """

    atomic = False

    dependencies = [
        ("posthog", "1118_subscriptiondelivery_change_summary"),
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
        migrations.SeparateDatabaseAndState(
            state_operations=[
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
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "posthog_user" '
                        'ADD COLUMN IF NOT EXISTS "onboarding_delegated_to_invite_id" uuid NULL; '
                        'ALTER TABLE "posthog_user" '
                        'ADD CONSTRAINT "posthog_user_onboarding_delegated_to_invite_id_fkey" '
                        'FOREIGN KEY ("onboarding_delegated_to_invite_id") '
                        'REFERENCES "posthog_organizationinvite"("id") ON DELETE SET NULL NOT VALID'
                    ),
                    reverse_sql=(
                        'ALTER TABLE "posthog_user" '
                        'DROP CONSTRAINT IF EXISTS "posthog_user_onboarding_delegated_to_invite_id_fkey"; '
                        'ALTER TABLE "posthog_user" DROP COLUMN IF EXISTS "onboarding_delegated_to_invite_id"'
                    ),
                ),
            ],
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
