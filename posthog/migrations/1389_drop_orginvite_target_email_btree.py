from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1388_activitylog_credential"),
    ]

    operations = [
        # Invite lookups use `target_email__iexact`, which `orginvite_upper_email_idx` serves.
        # The case-sensitive lookups filter by organization and use its index, so no read uses these.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="organizationinvite",
                    name="target_email",
                    field=models.EmailField(max_length=254, null=True),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="posthog_organizationinvite_target_email_45fa23f6_like",
                    table_name="posthog_organizationinvite",
                    columns="(target_email varchar_pattern_ops)",
                ),
                DropIndexConcurrently(
                    index_name="posthog_organizationinvite_target_email_45fa23f6",
                    table_name="posthog_organizationinvite",
                    columns="(target_email)",
                ),
            ],
        ),
    ]
