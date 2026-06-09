from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1217_project_is_pending_deletion"),
    ]

    operations = [
        # All three are metadata-only on PG 11+ (nullable, or a constant default), so no table
        # rewrite on posthog_organizationinvite. The scheduled_send_at index is added concurrently
        # in the next migration.
        migrations.AddField(
            model_name="organizationinvite",
            name="expires_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text=(
                    "When set, overrides the default created_at-based expiry. Extended each time the "
                    "invite email is postponed so the rescheduled link stays valid."
                ),
            ),
        ),
        migrations.AddField(
            model_name="organizationinvite",
            name="scheduled_send_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text=(
                    "When the next, postponed invite email is due. Null when nothing is scheduled. "
                    "Picked up by the send_scheduled_invites periodic task."
                ),
            ),
        ),
        migrations.AddField(
            model_name="organizationinvite",
            name="postpone_count",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="How many times this invite email has been postponed; drives a unique email campaign key per re-send.",
            ),
        ),
    ]
