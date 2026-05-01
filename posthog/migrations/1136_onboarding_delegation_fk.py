from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Add User.onboarding_delegated_to_invite (FK) with NOT VALID in separate migration.

    Split from 1135 so 1135 stays atomic with rollback; NOT VALID is safe in a transaction
    in PostgreSQL. Index is 1137_onboarding_delegated_to_invite_index (CONCURRENTLY).
    """

    dependencies = [
        ("posthog", "1135_onboarding_delegation_fields"),
    ]

    operations = [
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
    ]
