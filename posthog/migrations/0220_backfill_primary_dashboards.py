from django.db import connection, migrations, transaction


def backfill_primary_dashboards(apps, _):
    import structlog

    logger = structlog.get_logger(__name__)
    logger.info("starting 0220_set_primary_dashboard")

    Team = apps.get_model("posthog", "Team")

    team_dashboards = []
    with connection.cursor() as cursor:

        # Fetch a list of teams and the id of the dashboard that should be set as the primary dashboard
        # The primary dashboard should be the oldest pinned dashboard, if one exists
        # or the oldest dashboard, if no pinned dashboards exist
        # Notes:
        # - We use id as a proxy for dashboard age because dashboards use a simple incrementing id
        # - We ignore teams that already have a primary dashboard set
        cursor.execute(
            """
            SELECT posthog_team.id,
                COALESCE(
                    MIN(
                        CASE
                            WHEN posthog_dashboard.pinned THEN posthog_dashboard.id
                            ELSE NULL
                        END
                    ),
                    MIN(
                        CASE
                            WHEN NOT posthog_dashboard.pinned THEN posthog_dashboard.id
                            ELSE NULL
                        END
                    )
                ) AS primary_dashboard_id
            FROM posthog_team
            LEFT JOIN posthog_dashboard ON posthog_dashboard.team_id = posthog_team.id
            WHERE posthog_team.primary_dashboard_id IS NULL
            AND posthog_dashboard.id IS NOT NULL
            GROUP BY posthog_team.id
            """
        )
        team_dashboards = cursor.fetchall()

    num_teams_to_update = len(team_dashboards)
    logger.info(f"fetched {num_teams_to_update} teams")
    batch_size = 500

    # From the list fetched above, we now update the teams in batches of 500
    for i in range(0, num_teams_to_update, batch_size):
        team_dashboards_batch = team_dashboards[i : i + batch_size]
        logger.info(f"Updating team {i} to {i + batch_size}")
        # transaction.atomic() reduces our database overhead
        with transaction.atomic():
            for team_id, primary_dashboard_id in team_dashboards_batch:
                Team.objects.filter(id=team_id).update(primary_dashboard_id=primary_dashboard_id)
        logger.info(f"Successful update of team {i} to {i + batch_size}")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0219_migrate_tags_v2"),
    ]

    operations = [migrations.RunPython(backfill_primary_dashboards)]
