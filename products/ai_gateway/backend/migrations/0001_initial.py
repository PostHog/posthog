import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("posthog", "1404_organization_inactive_quota_index"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DevGatewayToken",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("client", models.CharField(choices=[("web", "Web"), ("cli", "CLI")], max_length=16)),
                ("cap_usd", models.DecimalField(decimal_places=2, max_digits=10)),
                ("token_hash", models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["team", "user", "created_at"], name="ai_gw_devtoken_user_created")],
            },
        ),
    ]
