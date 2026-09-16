import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1362_identity_provider_oidc")]

    operations = [
        migrations.CreateModel(
            name="TeamHeatmapConfig",
            fields=[
                (
                    "team",
                    models.OneToOneField(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="posthog.team",
                    ),
                ),
                (
                    "screenshot_secret",
                    models.CharField(blank=True, max_length=200, null=True),
                ),
            ],
        ),
    ]
