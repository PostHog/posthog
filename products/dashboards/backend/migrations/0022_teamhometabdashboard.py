import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1383_taggeditem_untrack_legacy_keys"),
        ("dashboards", "0021_drop_dashboardtemplate_github_url_column"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeamHomeTabDashboard",
            fields=[
                (
                    "team",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="posthog.team",
                    ),
                ),
                (
                    "dashboard",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="dashboards.dashboard",
                    ),
                ),
            ],
        ),
    ]
