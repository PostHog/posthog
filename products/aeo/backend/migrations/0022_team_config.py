import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("aeo", "0021_brand_pass_progress"),
        ("posthog", "1453_disable_activitylog_detail_gin_fastupdate"),
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
                    "max_active_prompts",
                    models.PositiveIntegerField(
                        db_default=100,
                        default=100,
                        help_text="How many unarchived prompts the project can keep turned on at once. Each one is checked by every enabled engine on its schedule.",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_aeo_team_config",
            },
        ),
    ]
