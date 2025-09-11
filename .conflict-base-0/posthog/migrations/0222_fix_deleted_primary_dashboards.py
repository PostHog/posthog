from django.db import connection, migrations
from django.db.models import Q

import structlog

# 0220_set_primary_dashboard set the primary dashboard for teams, but
# it didn't account for deleted dashboards. This migration fixes projects
# that have a primary dashboard set to a deleted dashboard.


def fix_for_deleted_primary_dashboards(apps, _):
    logger = structlog.get_logger(__name__)
    logger.info("starting 0222_fix_deleted_primary_dashboards")

    Team = apps.get_model("posthog", "Team")

    expected_team_dashboards = []
    with connection.cursor() as cursor:
        # Fetch a list of teams and the id of the dashboard that should be set as the primary dashboard
        # The primary dashboard should be the oldest pinned dashboard, if one exists
        # or the oldest dashboard, if no pinned dashboards exist
        # Notes:
        # - We use id as a proxy for dashboard age because dashboards use a simple incrementing id
        # - We ignore teams that already have a primary dashboard set
        # - Remove deleted dashboards
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
            INNER JOIN posthog_dashboard ON posthog_dashboard.team_id = posthog_team.id
            WHERE NOT posthog_dashboard.deleted
            GROUP BY posthog_team.id
            """
        )
        expected_team_dashboards = cursor.fetchall()

    team_to_primary_dashboard = dict(expected_team_dashboards)
    teams_to_update = Team.objects.filter(Q(primary_dashboard__deleted=True) | Q(primary_dashboard__isnull=True)).only(
        "id", "primary_dashboard_id"
    )
    for team in teams_to_update:
        team.primary_dashboard_id = team_to_primary_dashboard.get(team.id, None)
    Team.objects.bulk_update(teams_to_update, ["primary_dashboard_id"], batch_size=500)


# Because of the nature of this migration, there's no way to reverse it without potentially destroying customer data
# However, we still need a reverse function, so that we can rollback other migrations
def reverse(apps, _):
    pass


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0221_add_activity_log_model"),
    ]

    operations = [migrations.RunPython(fix_for_deleted_primary_dashboards, reverse, elidable=True)]
