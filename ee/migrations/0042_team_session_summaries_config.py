import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1094_oauth_provisioning_fields"),
        ("ee", "0041_migrate_dashboards_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeamSessionSummariesConfig",
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
                    "product_context",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text=(
                            "Free-form description of the team's product, used to tailor AI-generated session summaries. "
                            "Injected into the system prompt of every summary generated for this team."
                        ),
                        max_length=10000,
                    ),
                ),
            ],
        ),
    ]
