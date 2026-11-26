from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.facade.api import create_dashboard_from_tiles


def create_data_ops_dashboard(team: Team, user: User) -> int:
    """
    Creates the default data ops overview dashboard for a team.
    Seeded with a starter tile — users can add more to track sync health, row counts, etc.
    """
    dashboard = create_dashboard_from_tiles(
        team=team,
        user=user,
        name="Data ops overview",
        description="Your data ops overview. Add insights to track sync health, row counts, and anything else you care about.",
        filters={},
        tiles=[
            {
                "type": "INSIGHT",
                "name": "Events ingested",
                "description": "",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "kind": "EventsNode",
                                "math": "total",
                                "name": "All events",
                                "event": None,
                            }
                        ],
                        "version": 2,
                        "interval": "hour",
                        "dateRange": {
                            "date_to": None,
                            "date_from": "-24h",
                            "explicitDate": False,
                        },
                        "trendsFilter": {"display": "BoldNumber"},
                        "compareFilter": {"compare": True, "compare_to": "-1w"},
                    },
                },
                "layouts": {
                    "sm": {
                        "h": 3,
                        "w": 2,
                        "x": 0,
                        "y": 0,
                        "minH": 1,
                        "minW": 1,
                    },
                },
            },
        ],
        tags=[],
    )
    return dashboard.id
