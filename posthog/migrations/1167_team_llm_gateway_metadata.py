from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1166_oauth_impersonated_by"),
    ]

    operations = [
        # All three fields are nullable with no DB-level default so the
        # migration is metadata-only on PG 11+ (no table rewrite, no row
        # backfill, instant on the posthog_team table). Application code
        # treats null as "default tier, empty allowlist, not revoked".
        migrations.AddField(
            model_name="team",
            name="llm_gateway_allowed_models",
            field=models.JSONField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="team",
            name="llm_gateway_tier",
            field=models.CharField(
                max_length=32,
                choices=[("free", "Free"), ("pro", "Pro"), ("enterprise", "Enterprise")],
                null=True,
                blank=True,
            ),
        ),
        migrations.AddField(
            model_name="team",
            name="llm_gateway_revoked_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
