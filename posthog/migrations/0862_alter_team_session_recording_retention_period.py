from django.db import migrations, models

import structlog

logger = structlog.get_logger(__name__)


def migrate_replay_retention_period(apps, schema_editor):
    Team = apps.get_model("posthog", "Team")

    teams_to_migrate = []
    batch_size = 100

    for team in (
        Team.objects.filter(session_recording_retention_period="legacy")
        .only("id", "session_recording_retention_period")
        .iterator(chunk_size=batch_size)
    ):
        try:
            team.session_recording_retention_period = "30d"
            teams_to_migrate.append(team)

            if len(teams_to_migrate) >= batch_size:
                Team.objects.bulk_update(
                    teams_to_migrate,
                    ["session_recording_retention_period"],
                )
                print(f"Migrated {len(teams_to_migrate)} teams")  # noqa: T201
                teams_to_migrate = []
        except Exception as e:
            # If anything fails for a team, skip it and continue with others
            logger.error("replay_retention_period_migration_failed", team_id=team.id, error=str(e), exc_info=True)
            continue

    # Migrate any remaining teams
    Team.objects.bulk_update(
        teams_to_migrate,
        ["session_recording_retention_period"],
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0861_alter_survey_questions"),
    ]

    operations = [
        migrations.RunPython(migrate_replay_retention_period, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name="team",
            name="session_recording_retention_period",
            field=models.CharField(
                choices=[("30d", "30 Days"), ("90d", "90 Days"), ("1y", "1 Year"), ("5y", "5 Years")],
                default="30d",
                max_length=3,
            ),
        ),
    ]
