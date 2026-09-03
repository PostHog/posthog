import django.utils.timezone
import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1339_validate_taggeditem_project_fk"),
    ]

    operations = [
        migrations.CreateModel(
            name="HealthCheckRun",
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
                ("kind", models.CharField(max_length=100)),
                ("last_run_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("found_issues", models.BooleanField(default=False)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="health_check_runs",
                        to="posthog.team",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="healthcheckrun",
            constraint=models.UniqueConstraint(fields=("team", "kind"), name="unique_health_check_run_per_team_kind"),
        ),
    ]
