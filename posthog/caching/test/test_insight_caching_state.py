from datetime import timedelta
from typing import Any, Dict, Optional, Union, cast
from unittest.mock import patch

import pytest
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.caching.insight_caching_state import LazyLoader, TargetCacheAge, calculate_target_age
from posthog.models import Dashboard, DashboardTile, Insight, InsightViewed, Team, Text, User
from posthog.test.base import BaseTest

filter_dict = {
    "events": [{"id": "$pageview"}],
    "properties": [{"key": "$browser", "value": "Mac OS X"}],
}


class TestLazyLoader(BaseTest):
    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_recently_viewed_insights(self):
        insights = [Insight.objects.create(team=self.team) for _ in range(3)]
        user2 = User.objects.create(email="testuser@posthog.com")

        InsightViewed.objects.create(
            insight=insights[0],
            last_viewed_at=now() - timedelta(hours=50),
            user=self.user,
            team=self.team,
        )
        InsightViewed.objects.create(
            insight=insights[1],
            last_viewed_at=now() - timedelta(hours=50),
            user=self.user,
            team=self.team,
        )
        InsightViewed.objects.create(
            insight=insights[1],
            last_viewed_at=now() - timedelta(hours=35),
            user=user2,
            team=self.team,
        )
        InsightViewed.objects.create(
            insight=insights[2],
            last_viewed_at=now() - timedelta(hours=2),
            user=self.user,
            team=self.team,
        )

        self.assertEqual(LazyLoader().recently_viewed_insights, {insights[1].pk, insights[2].pk})


def create_insight(
    team: Team,
    user: User,
    mock_active_teams: Any,
    team_should_be_active=True,
    viewed_at_delta: Optional[timedelta] = timedelta(hours=1),  # noqa
    filters=filter_dict,
    deleted=False,
) -> Insight:
    mock_active_teams.return_value = {team.pk} if team_should_be_active else set()

    insight = Insight.objects.create(team=team, filters=filters, deleted=deleted)
    if viewed_at_delta is not None:
        InsightViewed.objects.create(insight=insight, last_viewed_at=now() - viewed_at_delta, user=user, team=team)

    return insight


def create_tile(
    team: Team,
    user: User,
    mock_active_teams: Any,
    on_home_dashboard=False,
    team_should_be_active=True,
    viewed_at_delta: Optional[timedelta] = None,
    insight_filters=filter_dict,
    insight_deleted=False,
    dashboard_deleted=False,
    text_tile=False,
) -> DashboardTile:
    mock_active_teams.return_value = {team.pk} if team_should_be_active else set()

    dashboard = Dashboard.objects.create(
        team=team, last_accessed_at=now() - viewed_at_delta if viewed_at_delta else None, deleted=dashboard_deleted
    )

    if on_home_dashboard:
        team.primary_dashboard_id = dashboard.pk
        team.save()

    insight = text = None
    if text_tile:
        text = Text.objects.create(team=team, body="Some text")
    else:
        insight = Insight.objects.create(team=team, filters=insight_filters, deleted=insight_deleted)

    return DashboardTile.objects.create(
        dashboard=dashboard,
        insight=insight,
        text=text,
    )


@pytest.mark.parametrize(
    "create_item,create_item_kw,expected_target_age",
    [
        # Insight test cases
        pytest.param(create_insight, {}, TargetCacheAge.MID_PRIORITY, id="insight base"),
        pytest.param(
            create_insight, {"team_should_be_active": False}, TargetCacheAge.NO_CACHING, id="insight with inactive team"
        ),
        pytest.param(create_insight, {"viewed_at_delta": None}, TargetCacheAge.NO_CACHING, id="insight never viewed"),
        pytest.param(
            create_insight,
            {"viewed_at_delta": timedelta(weeks=100)},
            TargetCacheAge.NO_CACHING,
            id="insight viewed long time ago",
        ),
        pytest.param(create_insight, {"filters": {}}, TargetCacheAge.NO_CACHING, id="insight with no filters"),
        pytest.param(create_insight, {"deleted": True}, TargetCacheAge.NO_CACHING, id="deleted insight"),
        # Dashboard tile test cases
        pytest.param(create_tile, {}, TargetCacheAge.LOW_PRIORITY, id="tile base"),
        pytest.param(
            create_tile, {"team_should_be_active": False}, TargetCacheAge.NO_CACHING, id="tile with inactive team"
        ),
        pytest.param(
            create_tile, {"dashboard_deleted": True}, TargetCacheAge.NO_CACHING, id="tile with deleted dashboard"
        ),
        pytest.param(create_tile, {"insight_deleted": True}, TargetCacheAge.NO_CACHING, id="tile with deleted insight"),
        pytest.param(
            create_tile, {"insight_filters": {}}, TargetCacheAge.NO_CACHING, id="tile with insight with no filters"
        ),
        pytest.param(create_tile, {"text_tile": True}, TargetCacheAge.NO_CACHING, id="tile with text"),
        pytest.param(
            create_tile, {"on_home_dashboard": True}, TargetCacheAge.HIGH_PRIORITY, id="tile on home dashboard"
        ),
        pytest.param(
            create_tile,
            {"viewed_at_delta": timedelta(hours=12)},
            TargetCacheAge.HIGH_PRIORITY,
            id="very recently viewed tile (1)",
        ),
        pytest.param(
            create_tile,
            {"viewed_at_delta": timedelta(hours=37)},
            TargetCacheAge.HIGH_PRIORITY,
            id="very recently viewed tile (2)",
        ),
        pytest.param(
            create_tile,
            {"viewed_at_delta": timedelta(hours=50)},
            TargetCacheAge.MID_PRIORITY,
            id="recently viewed tile (1)",
        ),
        pytest.param(
            create_tile,
            {"viewed_at_delta": timedelta(days=10)},
            TargetCacheAge.MID_PRIORITY,
            id="recently viewed tile (2)",
        ),
        pytest.param(
            create_tile, {"viewed_at_delta": timedelta(days=20)}, TargetCacheAge.LOW_PRIORITY, id="tile viewed ages ago"
        ),
    ],
)
@pytest.mark.django_db
@patch("posthog.caching.insight_caching_state.active_teams")
def test_calculate_target_age(
    mock_active_teams, team: Team, user: User, create_item, create_item_kw: Dict, expected_target_age: TargetCacheAge
):
    item = cast(
        Union[Insight, DashboardTile],
        create_item(team=team, user=user, mock_active_teams=mock_active_teams, **create_item_kw),
    )
    target_age = calculate_target_age(team, item, LazyLoader())
    assert target_age == expected_target_age
