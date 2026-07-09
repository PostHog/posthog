import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1230_duckgresserver_bucket"),
    ]

    operations = [
        migrations.CreateModel(
            name="DuckgresServerTeam",
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
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="posthog.user",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True, blank=True)),
                (
                    "server",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="teams",
                        to="posthog.duckgresserver",
                    ),
                ),
                (
                    "team",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="duckgres_server_team",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_duckgresserverteam",
                "verbose_name": "Duckgres server team",
                "verbose_name_plural": "Duckgres server teams",
            },
        ),
        migrations.AddField(
            model_name="ducklakebackfill",
            name="table_suffix",
            field=models.CharField(
                blank=True,
                help_text="Suffix for this team's warehouse tables in the duckling (events_<suffix>, persons_<suffix>). "
                "User-supplied; falls back to the shared tables when unset.",
                max_length=63,
                null=True,
            ),
        ),
    ]
