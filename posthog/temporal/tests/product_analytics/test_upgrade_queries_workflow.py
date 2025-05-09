import pytest

from posthog.models.insight import Insight
from posthog.temporal.product_analytics.upgrade_queries_workflow import get_insights_to_migrate


@pytest.mark.django_db(transaction=True)
def test_get_insights_to_migrate(activity_environment, team):
    # TODO: Mock InsightVizNode v3 and TrendsQuery v5, EventsNode v7
    # TODO: Capture SQL

    # all versions satisfied
    Insight.objects.create(
        query={
            "kind": "InsightVizNode",
            "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview", "v": 8}], "v": 6},
            "v": 4,
        },
        team=team,
    )

    # matching top-level node (InsightVizNode)
    m1 = Insight.objects.create(
        query={
            "kind": "InsightVizNode",
            "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview", "v": 8}], "v": 6},
            "v": 3,
        },
        team=team,
    )

    # matching node in nested dict (TrendsQuery)
    m2 = Insight.objects.create(
        query={
            "kind": "InsightVizNode",
            "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview", "v": 8}], "v": 5},
            "v": 4,
        },
        team=team,
    )

    # matching node in nested list (EventsNode)
    m3 = Insight.objects.create(
        query={
            "kind": "InsightVizNode",
            "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview", "v": 7}], "v": 6},
            "v": 4,
        },
        team=team,
    )

    # no query
    Insight.objects.create(team=team)

    # kind without migration (DataTableNode)
    Insight.objects.create(
        query={
            "kind": "DataTableNode",
        },
        team=team,
    )

    # no version (InsightVizNode)
    m4 = Insight.objects.create(
        query={
            "kind": "InsightVizNode",
            "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview", "v": 8}], "v": 6},
        },
        team=team,
    )

    result = activity_environment.run(get_insights_to_migrate)

    expected_ids = [m1.id, m2.id, m3.id, m4.id]
    assert result == expected_ids
