from django.db import migrations, models
import django.contrib.postgres.fields
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0785_team_drop_events_older_than_seconds"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationSetting",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("setting_key", models.CharField(max_length=100)),
                ("setting_value", django.contrib.postgres.fields.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="settings", to="posthog.organization"),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name="created_organization_settings",
                        to="posthog.user",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name="updated_organization_settings",
                        to="posthog.user",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_organization_settings",
            },
        ),
        migrations.AddIndex(
            model_name="organizationsetting",
            index=models.Index(fields=["organization", "setting_key"], name="posthog_org_organi_123456_idx"),
        ),
        migrations.AddIndex(
            model_name="organizationsetting",
            index=models.Index(fields=["setting_key"], name="posthog_org_settin_123456_idx"),
        ),
        migrations.AddConstraint(
            model_name="organizationsetting",
            constraint=models.UniqueConstraint(
                fields=["organization", "setting_key"], name="unique_organization_setting"
            ),
        ),
    ]
