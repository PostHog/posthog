# Generated manually — `SocialReferral` model

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1152_fix_device_bucketing_persist_across_auth"),
    ]

    operations = [
        migrations.CreateModel(
            name="SocialReferral",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "referee_state",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text='Per-invited-org map: `{ "<organization_uuid>": { "first_event_sent": boolean } }`.',
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="social_referrals",
                        to="posthog.organization",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        help_text="User who generated this referral link.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "posthog_social_referral",
                "indexes": [
                    models.Index(
                        fields=["organization", "-created_at"],
                        name="social_ref_org_created_idx",
                    )
                ],
            },
        ),
    ]
