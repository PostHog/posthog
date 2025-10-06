from datetime import timedelta
from typing import Any, Optional, Union, cast

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils.timezone import now

from posthog.caching.insight_caching_state import (
    LazyLoader,
    TargetCacheAge,
    calculate_target_age,
    sync_insight_cache_states,
    upsert,
)
from posthog.models import (
    Dashboard,
    DashboardTile,
    Insight,
    InsightCachingState,
    InsightViewed,
    SharingConfiguration,
    Team,
    Text,
    User,
)
from posthog.models.signals import mute_selected_signals

filter_dict = {
    "events": [{"id": "$pageview"}],
    "properties": [{"key": "$browser", "value": "Mac OS X"}],
}


def create_insight(
    team: Team,
    user: User,
    mock_active_teams: Any = None,
    team_should_be_active=True,
    viewed_at_delta: Optional[timedelta] = timedelta(hours=1),  # noqa
    is_shared=True,
    filters=filter_dict,
    deleted=False,
    query: Optional[dict] = None,
) -> Insight:
    if mock_active_teams:
        mock_active_teams.return_value = {team.pk} if team_should_be_active else set()

    if query is not None:
        filters = {}

    insight = Insight.objects.create(team=team, filters=filters, deleted=deleted, query=query)
    if viewed_at_delta is not None:
        InsightViewed.objects.create(
            insight=insight,
            last_viewed_at=now() - viewed_at_delta,
            user=user,
            team=team,
        )
    if is_shared:
        SharingConfiguration.objects.create(team=team, insight=insight, enabled=True)

    return insight


def create_tile(
    team: Team,
    user: User,
    mock_active_teams: Any = None,
    on_home_dashboard=False,
    team_should_be_active=True,
    viewed_at_delta: Optional[timedelta] = None,
    insight_filters=filter_dict,
    insight_deleted=False,
    dashboard_deleted=False,
    dashboard_tile_deleted=False,
    is_dashboard_shared=True,
    text_tile=False,
    query: Optional[dict] = None,
) -> DashboardTile:
    if mock_active_teams:
        mock_active_teams.return_value = {team.pk} if team_should_be_active else set()

    dashboard = Dashboard.objects.create(
        team=team,
        last_accessed_at=now() - viewed_at_delta if viewed_at_delta else None,
        deleted=dashboard_deleted,
    )

    if on_home_dashboard:
        team.primary_dashboard_id = dashboard.pk
        team.save()

    if is_dashboard_shared:
        SharingConfiguration.objects.create(team=team, dashboard=dashboard, enabled=True)

    insight = text = None
    if text_tile:
        text = Text.objects.create(team=team, body="Some text")
    else:
        if query is not None:
            insight_filters = {}
        insight = Insight.objects.create(team=team, filters=insight_filters, deleted=insight_deleted, query=query)

    return DashboardTile.objects.create(
        dashboard=dashboard,
        insight=insight,
        text=text,
        deleted=dashboard_tile_deleted,
    )


@pytest.mark.parametrize(
    "create_item,create_item_kw,expected_target_age",
    [
        # Insight test cases
        pytest.param(create_insight, {}, TargetCacheAge.MID_PRIORITY, id="shared insight (base)"),
        pytest.param(
            create_insight,
            {"is_shared": False},
            TargetCacheAge.NO_CACHING,
            id="not shared insight",
        ),
        pytest.param(
            create_insight,
            {"team_should_be_active": False},
            TargetCacheAge.NO_CACHING,
            id="insight with inactive team",
        ),
        pytest.param(
            create_insight,
            {"viewed_at_delta": None},
            TargetCacheAge.NO_CACHING,
            id="insight never viewed",
        ),
        pytest.param(
            create_insight,
            {"viewed_at_delta": timedelta(weeks=100)},
            TargetCacheAge.NO_CACHING,
            id="insight viewed long time ago",
        ),
        pytest.param(
            create_insight,
            {"filters": {}},
            TargetCacheAge.NO_CACHING,
            id="insight with no filters",
        ),
        pytest.param(
            create_insight,
            {"deleted": True},
            TargetCacheAge.NO_CACHING,
            id="deleted insight",
        ),
        # Dashboard tile test cases
        pytest.param(create_tile, {}, TargetCacheAge.HIGH_PRIORITY, id="shared tile (base)"),
        pytest.param(
            create_tile,
            {"is_dashboard_shared": False},
            TargetCacheAge.NO_CACHING,
            id="not shared tile",
        ),
        pytest.param(
            create_tile,
            {"team_should_be_active": False},
            TargetCacheAge.NO_CACHING,
            id="tile with inactive team",
        ),
        pytest.param(
            create_tile,
            {"dashboard_tile_deleted": True},
            TargetCacheAge.NO_CACHING,
            id="deleted tile",
        ),
        pytest.param(
            create_tile,
            {"dashboard_deleted": True},
            TargetCacheAge.NO_CACHING,
            id="tile with deleted dashboard",
        ),
        pytest.param(
            create_tile,
            {"insight_deleted": True},
            TargetCacheAge.NO_CACHING,
            id="tile with deleted insight",
        ),
        pytest.param(
            create_tile,
            {"insight_filters": {}},
            TargetCacheAge.NO_CACHING,
            id="tile with insight with no filters",
        ),
        pytest.param(
            create_tile,
            {"text_tile": True},
            TargetCacheAge.NO_CACHING,
            id="tile with text",
        ),
        pytest.param(
            create_tile,
            {"on_home_dashboard": True},
            TargetCacheAge.HIGH_PRIORITY,
            id="tile on home dashboard",
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
            create_tile,
            {"viewed_at_delta": timedelta(days=20), "is_dashboard_shared": True},
            TargetCacheAge.HIGH_PRIORITY,
            id="shared tile viewed ages ago",
        ),
        pytest.param(
            create_tile,
            {"viewed_at_delta": timedelta(days=20), "is_dashboard_shared": False},
            TargetCacheAge.NO_CACHING,
            id="tile viewed ages ago",
        ),
        # cacheable types of query
        pytest.param(
            create_insight,
            {"query": {"kind": "EventsQuery", "select": []}, "viewed_at_delta": timedelta(days=1)},
            TargetCacheAge.MID_PRIORITY,
            id="insight with EventsQuery query viewed recently",
        ),
        pytest.param(
            create_insight,
            {"query": {"kind": "HogQLQuery", "query": ""}, "viewed_at_delta": timedelta(days=1)},
            TargetCacheAge.MID_PRIORITY,
            id="insight with HogQLQuery query viewed recently",
        ),
        # other types of query aren't cacheable
        pytest.param(
            create_insight,
            {
                "query": {"kind": "TimeToSeeDataSessionsQuery"},
                "viewed_at_delta": timedelta(days=1),
            },
            TargetCacheAge.NO_CACHING,
            id="insight with TimeToSeeDataSessionsQuery query viewed recently",
        ),
        pytest.param(
            create_insight,
            {
                "query": {"kind": "TimeToSeeDataQuery"},
                "viewed_at_delta": timedelta(days=1),
            },
            TargetCacheAge.NO_CACHING,
            id="insight with TimeToSeeDataQuery query viewed recently",
        ),
        pytest.param(
            create_insight,
            {"query": {"kind": "something else"}, "viewed_at_delta": timedelta(days=1)},
            TargetCacheAge.NO_CACHING,
            id="insight with query viewed recently but not a cacheable type of query",
        ),
        # unless they have cacheable source
        pytest.param(
            create_insight,
            {
                "query": {"kind": "something else", "source": {"kind": "EventsQuery", "select": []}},
                "viewed_at_delta": timedelta(days=1),
            },
            TargetCacheAge.MID_PRIORITY,
            id="insight with query viewed recently, not a cacheable type of query, but with a cacheable source",
        ),
        pytest.param(
            create_tile,
            {
                "query": {"kind": "EventsQuery", "select": []},
                "viewed_at_delta": timedelta(days=20),
                "is_dashboard_shared": False,
            },
            TargetCacheAge.NO_CACHING,
            id="tile with query viewed ages ago",
        ),
        pytest.param(
            create_tile,
            {
                "query": {"kind": "EventsQuery", "select": []},
                "viewed_at_delta": timedelta(days=20),
                "is_dashboard_shared": True,
            },
            TargetCacheAge.HIGH_PRIORITY,
            id="shared tile with query viewed ages ago",
        ),
    ],
)
@pytest.mark.django_db
@patch("posthog.caching.insight_caching_state.active_teams")
def test_calculate_target_age(
    mock_active_teams,
    team: Team,
    user: User,
    create_item,
    create_item_kw: dict,
    expected_target_age: TargetCacheAge,
):
    item = cast(
        Union[Insight, DashboardTile],
        create_item(team=team, user=user, mock_active_teams=mock_active_teams, **create_item_kw),
    )
    target_age = calculate_target_age(team, item, LazyLoader())
    assert target_age == expected_target_age


@pytest.mark.django_db
@patch("posthog.caching.insight_caching_state.active_teams")
def test_upsert_new_insight(mock_active_teams, team: Team, user: User):
    with mute_selected_signals():
        insight = create_insight(team=team, user=user, mock_active_teams=mock_active_teams)
    upsert(team, insight)

    assert InsightCachingState.objects.filter(team=team).count() == 1
    caching_state = InsightCachingState.objects.get(team=team)

    assert caching_state is not None
    assert caching_state.team_id == team.pk
    assert caching_state.insight == insight
    assert caching_state.dashboard_tile is None
    assert isinstance(caching_state.cache_key, str)
    assert caching_state.target_cache_age_seconds == TargetCacheAge.MID_PRIORITY.value.total_seconds()
    assert caching_state.last_refresh is None
    assert caching_state.last_refresh_queued_at is None
    assert caching_state.refresh_attempt == 0


@pytest.mark.django_db
@patch("posthog.caching.insight_caching_state.active_teams")
def test_upsert_update_insight(mock_active_teams, team: Team, user: User):
    with mute_selected_signals():
        insight = create_insight(team=team, user=user, mock_active_teams=mock_active_teams)
    upsert(team, insight)

    caching_state = InsightCachingState.objects.get(team=team)
    caching_state.last_refresh = now()
    caching_state.last_refresh_queued_at = now()
    caching_state.refresh_attempt = 1
    caching_state.save()

    with mute_selected_signals():
        insight.deleted = True
        insight.save()

    upsert(team, insight)
    updated_caching_state = InsightCachingState.objects.get(team=team)

    assert InsightCachingState.objects.filter(team=team).count() == 1
    assert updated_caching_state is not None
    assert updated_caching_state.cache_key == caching_state.cache_key
    assert updated_caching_state.target_cache_age_seconds is None
    assert updated_caching_state.last_refresh == caching_state.last_refresh
    assert updated_caching_state.last_refresh_queued_at == caching_state.last_refresh_queued_at
    assert updated_caching_state.refresh_attempt == 1


@pytest.mark.django_db
@patch("posthog.caching.insight_caching_state.active_teams")
def test_upsert_update_insight_with_filter_change(mock_active_teams, team: Team, user: User):
    with mute_selected_signals():
        insight = create_insight(team=team, user=user, mock_active_teams=mock_active_teams)

    upsert(team, insight)

    caching_state = InsightCachingState.objects.get(team=team)
    caching_state.last_refresh = now()
    caching_state.refresh_attempt = 1
    caching_state.save()

    with mute_selected_signals():
        insight.filters = {
            **filter_dict,
            "events": [{"id": "$pageleave"}],
        }
        insight.save()

    upsert(team, insight)
    updated_caching_state = InsightCachingState.objects.get(team=team)

    assert InsightCachingState.objects.filter(team=team).count() == 1
    assert updated_caching_state is not None
    assert updated_caching_state.cache_key != caching_state.cache_key
    assert updated_caching_state.target_cache_age_seconds is not None
    assert updated_caching_state.last_refresh is None
    assert updated_caching_state.last_refresh_queued_at is None
    assert updated_caching_state.refresh_attempt == 0


@pytest.mark.django_db
@patch("posthog.caching.insight_caching_state.active_teams")
def test_upsert_new_tile(mock_active_teams, team: Team, user: User):
    with mute_selected_signals():
        tile = create_tile(team=team, user=user, mock_active_teams=mock_active_teams)
    upsert(team, tile)

    assert InsightCachingState.objects.filter(team=team).count() == 1

    caching_state = InsightCachingState.objects.get(team=team)
    assert caching_state is not None
    assert caching_state.team_id == team.pk
    assert caching_state.insight == tile.insight
    assert caching_state.dashboard_tile == tile
    assert isinstance(caching_state.cache_key, str)
    assert caching_state.target_cache_age_seconds == TargetCacheAge.HIGH_PRIORITY.value.total_seconds()
    assert caching_state.last_refresh is None
    assert caching_state.last_refresh_queued_at is None
    assert caching_state.refresh_attempt == 0


@pytest.mark.django_db
@patch("posthog.caching.insight_caching_state.active_teams")
def test_upsert_text_tile_does_not_create_record(mock_active_teams, team: Team, user: User):
    tile = create_tile(team=team, user=user, mock_active_teams=mock_active_teams, text_tile=True)
    upsert(team, tile)

    assert InsightCachingState.objects.filter(team=team).count() == 0


@pytest.mark.django_db
@freeze_time("2020-01-04T13:01:01Z")
def test_sync_insight_cache_states(team: Team, user: User):
    with mute_selected_signals():
        create_insight(team=team, user=user)
        create_tile(team=team, user=user)

    sync_insight_cache_states()

    assert InsightCachingState.objects.filter(team=team).count() == 3


@pytest.mark.django_db
@freeze_time("2020-01-04T13:01:01Z")
def test_insight_cache_states_when_deleted_insight(team: Team, user: User):
    with mute_selected_signals():
        insight = create_insight(team=team, user=user)

    assert InsightCachingState.objects.filter(team=team, insight_id=insight.id).count() == 0

    # after sync we have a record for the insight
    sync_insight_cache_states()
    assert InsightCachingState.objects.filter(team=team, insight_id=insight.id).count() == 1

    # soft-deleting the insight *does not* cascade to the caching state
    insight.deleted = True
    insight.save()

    assert InsightCachingState.objects.filter(team=team, insight_id=insight.id).count() == 1

    # periodic sync sets to no caching
    sync_insight_cache_states()
    single_match = InsightCachingState.objects.filter(team=team, insight_id=insight.id).first()
    assert single_match is not None
    assert single_match.target_cache_age_seconds is None


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
