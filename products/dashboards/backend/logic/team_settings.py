from django.db import connection

from products.dashboards.backend.models.team_home_tab_dashboard_config import TeamHomeTabDashboardConfig


def home_tab_dashboard_id(*, team_id: int) -> int | None:
    config = TeamHomeTabDashboardConfig.objects.for_team(team_id).select_related("dashboard").first()
    dashboard = config.dashboard if config else None
    return dashboard.id if dashboard and not dashboard.deleted and dashboard.team_id == team_id else None


def set_home_tab_dashboard(*, team_id: int, dashboard_id: int | None) -> None:
    config, _ = TeamHomeTabDashboardConfig.objects.for_team(team_id).get_or_create(team_id=team_id)
    config.dashboard_id = dashboard_id
    config.save(update_fields=["dashboard"])


def remove_quick_filter_from_dashboards(*, team_id: int, quick_filter_id: str) -> int:
    with connection.cursor() as cursor:
        # Rebuilds each matching dashboard's JSONB array without the id. jsonb_agg returns NULL when
        # no element is left, so COALESCE keeps an empty array instead.
        cursor.execute(
            """
            UPDATE posthog_dashboard
            SET quick_filter_ids = COALESCE(
                (
                    SELECT jsonb_agg(elem)
                    FROM jsonb_array_elements(quick_filter_ids) AS elem
                    WHERE elem::text != %s
                ),
                '[]'::jsonb
            )
            WHERE team_id = %s
              AND quick_filter_ids IS NOT NULL
              AND quick_filter_ids @> %s::jsonb
            """,
            [f'"{quick_filter_id}"', team_id, f'["{quick_filter_id}"]'],
        )
        return cursor.rowcount
