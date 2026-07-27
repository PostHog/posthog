from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1195_alter_batchexportdestination_type"),
    ]

    operations = [
        # Nullable with no DB-level default so this is metadata-only on PG 11+
        # (no table rewrite, no row backfill, instant on posthog_team). Null
        # means "not enrolled" — pairs with llm_gateway_revoked_at; the
        # gateway admits only when enabled_at is set and revoked_at is null.
        migrations.AddField(
            model_name="team",
            name="llm_gateway_enabled_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
