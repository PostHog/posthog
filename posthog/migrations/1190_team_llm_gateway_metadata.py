from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1189_file_system_shortcut_order_index"),
    ]

    operations = [
        # Nullable with no DB-level default so the migration is metadata-only on
        # PG 11+ (no table rewrite, no row backfill, instant on posthog_team).
        # Null means "not revoked".
        migrations.AddField(
            model_name="team",
            name="llm_gateway_revoked_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
