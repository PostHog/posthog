import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("aeo", "0018_check_facts"),
        ("posthog", "1453_disable_activitylog_detail_gin_fastupdate"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AEOTeamConfig",
            fields=[
                (
                    "team",
                    models.OneToOneField(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="+",
                        serialize=False,
                        to="posthog.team",
                    ),
                ),
                (
                    "enabled_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When a setup first turned on scheduled checks. Null until then.",
                        null=True,
                    ),
                ),
                (
                    "enabled_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "AEO team config",
                "db_table": "posthog_aeo_team_config",
            },
        ),
    ]
