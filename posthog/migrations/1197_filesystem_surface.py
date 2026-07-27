from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1196_team_llm_gateway_enabled_at"),
    ]

    operations = [
        # Nullable with no DB-level default so the migration is metadata-only on
        # PG 11+ (no table rewrite, no row backfill). Legacy rows stay NULL and are
        # read as the default surface ("web") in code.
        migrations.AddField(
            model_name="filesystem",
            name="surface",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
