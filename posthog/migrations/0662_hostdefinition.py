from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0661_errortrackingissuefingerprintv2_first_seen"),
    ]

    operations = [
        migrations.CreateModel(
            name="HostDefinition",
            fields=[
                (
                    "id",
                    models.UUIDField(primary_key=True, serialize=False),
                ),
                ("host", models.CharField(max_length=400)),
                ("team", models.ForeignKey(on_delete=models.deletion.CASCADE, to="posthog.Team")),
                ("project", models.ForeignKey(null=True, on_delete=models.deletion.CASCADE, to="posthog.Project")),
                ("last_seen_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "posthog_hostdefinition",
            },
        ),
        migrations.AddIndex(
            model_name="hostdefinition",
            index=models.Index(
                fields=["team", "project", "host"],
                name="posthog_hostdefinition_team_project_host_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="hostdefinition",
            constraint=models.UniqueConstraint(
                fields=["team", "project", "host"],
                name="posthog_hostdefinition_team_project_host_uniq",
            ),
        ),
        # Note: We can't directly create a coalesced index in Django migrations
        # We need to use raw SQL for this
        migrations.RunSQL(
            sql="""
            CREATE UNIQUE INDEX posthog_hostdefinition_proj_uniq
            ON posthog_hostdefinition (coalesce(project_id, team_id), host)
            """,
            reverse_sql="DROP INDEX posthog_hostdefinition_proj_uniq",
        ),
    ]
