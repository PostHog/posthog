from copy import copy
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytz
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.constants import ENTITY_ID, ENTITY_TYPE, INSIGHT_STICKINESS
from posthog.decorators import CacheType
from posthog.models import Dashboard, DashboardTile, Filter, Insight
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.utils import get_filter
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.team.team import Team
from posthog.queries.util import get_earliest_timestamp
from posthog.tasks.update_cache import (
    PARALLEL_INSIGHT_CACHE,
    synchronously_update_insight_cache,
    update_cache_item,
    update_cached_items,
)
from posthog.test.base import APIBaseTest
from posthog.types import FilterType
from posthog.utils import generate_cache_key, get_safe_cache


def create_shared_dashboard(team: Team, is_shared: bool = False, **kwargs: Any) -> Dashboard:
    dashboard = Dashboard.objects.create(team=team, **kwargs)
    SharingConfiguration.objects.create(team=team, dashboard=dashboard, enabled=is_shared)

    return dashboard


def create_shared_insight(team: Team, is_shared: bool = False, **kwargs: Any) -> Insight:
    insight = Insight.objects.create(team=team, **kwargs)
    SharingConfiguration.objects.create(team=team, insight=insight, enabled=is_shared)

    return insight


def _a_dashboard_tile_with_known_last_refresh(team: Team, last_refresh_date: Optional[datetime]) -> DashboardTile:
    dashboard = create_shared_dashboard(team=team, is_shared=True)
    filter = {"events": [{"id": "$pageview"}]}
    item = Insight.objects.create(filters=filter, team=team)
    tile: DashboardTile = DashboardTile.objects.create(insight=item, dashboard=dashboard)
    tile.last_refresh = last_refresh_date
    tile.save(update_fields=["last_refresh"])
    return tile


def _create_insight_with_known_cache_key(team: Team, cache_key: Optional[str] = None) -> Insight:
    filter_dict: Dict[str, Any] = {
        "events": [{"id": "$pageview"}],
        "properties": [{"key": "$browser", "value": "Mac OS X"}],
    }
    insight: Insight = Insight.objects.create(team=team, filters=filter_dict)
    if cache_key:
        insight.filters_hash = cache_key
        insight.save(update_fields=["filters_hash"])

        insight.refresh_from_db()
        assert insight.filters_hash == cache_key

    return insight


def _create_dashboard_tile_with_known_cache_key(
    team: Team,
    insight: Insight,
    cache_key: Optional[str] = None,
    dashboard_filters: Optional[Dict] = None,
    last_accessed_at: Optional[datetime] = None,
) -> Tuple[Dashboard, DashboardTile]:
    dashboard: Dashboard = Dashboard.objects.create(
        team=team, filters=dashboard_filters if dashboard_filters else {}, last_accessed_at=last_accessed_at
    )

    tile: DashboardTile = DashboardTile.objects.create(insight=insight, dashboard=dashboard)
    if cache_key:
        tile.filters_hash = cache_key
        tile.save(update_fields=["filters_hash"])

        tile.refresh_from_db()
        insight.refresh_from_db()
        assert tile.filters_hash == cache_key
        assert insight.filters_hash == cache_key

    return dashboard, tile


class TestSynchronousCacheUpdate(APIBaseTest):
    @patch("posthog.tasks.update_cache.statsd.incr")
    def test_update_insight_cache_reports_on_updating_tiles_with_no_hash(self, statsd_incr: MagicMock) -> None:
        tile = _a_dashboard_tile_with_known_last_refresh(self.team, last_refresh_date=None)
        # can't set filters_hash=None on a route that triggers save
        DashboardTile.objects.filter(id=tile.id).update(filters_hash=None)
        tile.refresh_from_db()
        assert tile.filters_hash is None

        synchronously_update_insight_cache(tile.insight, tile.dashboard)

        statsd_incr.assert_any_call("update_cache_queue.set_missing_filters_hash", 1)

        tile.refresh_from_db()
        assert tile.filters_hash is not None

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_update_insight_filters_hash(self) -> None:
        test_hash = "rongi rattad ragisevad"
        insight = _create_insight_with_known_cache_key(self.team, test_hash)

        synchronously_update_insight_cache(insight, None)

        insight.refresh_from_db()
        assert insight.filters_hash != test_hash
        assert insight.last_refresh.isoformat(), "2021-08-25T22:09:14.252000+00:00"

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_update_dashboard_tile_updates_tile_and_insight_filters_hash_when_dashboard_has_no_filters(self) -> None:
        test_hash = "rongi rattad ragisevad"
        insight = _create_insight_with_known_cache_key(self.team, test_hash)
        dashboard, tile = _create_dashboard_tile_with_known_cache_key(self.team, insight, test_hash)

        synchronously_update_insight_cache(insight, dashboard)

        insight.refresh_from_db()
        tile.refresh_from_db()
        assert insight.filters_hash != test_hash
        assert insight.last_refresh.isoformat(), "2021-08-25T22:09:14.252000+00:00"
        assert tile.filters_hash != test_hash
        assert tile.last_refresh.isoformat() == "2021-08-25T22:09:14.252000+00:00"

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_update_dashboard_tile_updates_only_tile_when_different_filters(self) -> None:
        test_hash = "rongi rattad ragisevad"
        insight = _create_insight_with_known_cache_key(self.team, test_hash)
        dashboard, tile = _create_dashboard_tile_with_known_cache_key(
            self.team, insight, test_hash, dashboard_filters={"date_from": "-30d"}
        )

        synchronously_update_insight_cache(insight, dashboard)

        tile.refresh_from_db()
        insight.refresh_from_db()

        assert insight.filters_hash == test_hash
        assert insight.last_refresh is None
        assert tile.filters_hash != test_hash
        assert tile.last_refresh.isoformat() == "2021-08-25T22:09:14.252000+00:00"


class TestUpdateCache(APIBaseTest):
    @patch("posthog.tasks.update_cache.group.apply_async")
    @patch("posthog.celery.update_cache_item_task.s")
    def test_refresh_dashboard_cache(self, patch_update_cache_item: MagicMock, _: MagicMock) -> None:
        # There's two things we want to refresh
        # Any shared dashboard, as we only use cached items to show those
        # Any dashboard accessed in the last 7 days
        filter_dict: Dict[str, Any] = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }
        filter = Filter(data=filter_dict)
        shared_dashboard_with_no_filters = create_shared_dashboard(
            team=self.team, is_shared=True, last_accessed_at="2020-01-01T12:00:00Z"
        )
        funnel_filter = Filter(data={"events": [{"id": "user signed up", "type": "events", "order": 0},],})

        # we don't want insight and tile to have the same id,
        # or we can accidentally select the insight by selecting the tile
        some_different_filters = copy(filter_dict)
        some_different_filters.update({"date_from": "-14d"})
        Insight.objects.create(filters=some_different_filters, team=self.team)

        cached_insight_because_no_dashboard_filters = Insight.objects.create(
            filters=filter.to_dict(),
            team=self.team,
            name="trend cached because on shared dashboard with no dashboard filters",
        )
        cached_trend_tile_because_no_dashboard_filters = DashboardTile.objects.create(
            insight=cached_insight_because_no_dashboard_filters, dashboard=shared_dashboard_with_no_filters
        )
        cached_funnel_item = Insight.objects.create(
            filters=funnel_filter.to_dict(),
            team=self.team,
            name="funnel cached because on shared dashboard with no dashboard filters",
        )
        cached_funnel_tile_because_on_shared_dashboard = DashboardTile.objects.create(
            insight=cached_funnel_item, dashboard=shared_dashboard_with_no_filters
        )

        another_shared_dashboard_to_cache = create_shared_dashboard(
            team=self.team, is_shared=True, last_accessed_at=now()
        )
        insight_not_cached_because_dashboard_has_filters = Insight.objects.create(
            filters=Filter(data={"events": [{"id": "insight_not_cached_because_dashboard_has_filters"}]}).to_dict(),
            team=self.team,
            name="insight_not_cached_because_dashboard_has_filters",
        )
        tile_cached_because_dashboard_is_shared = DashboardTile.objects.create(
            insight=insight_not_cached_because_dashboard_has_filters, dashboard=another_shared_dashboard_to_cache
        )
        # filters changed after dashboard linked to insight but should still affect filters hash
        another_shared_dashboard_to_cache.filters = {"date_from": "-14d"}
        another_shared_dashboard_to_cache.save()

        dashboard_do_not_cache = create_shared_dashboard(
            team=self.team, is_shared=False, last_accessed_at="2020-01-01T12:00:00Z"
        )
        insight_not_cached_because_dashboard_unshared_and_not_recently_accessed = Insight.objects.create(
            filters=Filter(
                data={"events": [{"id": "insight_not_cached_because_dashboard_unshared_and_not_recently_accessed"}]}
            ).to_dict(),
            team=self.team,
        )
        tile_to_not_cache_because_dashboard_is_access_too_long_ago = DashboardTile.objects.create(
            insight=insight_not_cached_because_dashboard_unshared_and_not_recently_accessed,
            dashboard=dashboard_do_not_cache,
        )

        recently_accessed_unshared_dashboard_should_cache = create_shared_dashboard(
            team=self.team, is_shared=False, last_accessed_at=now()
        )
        item_cached_because_on_recently_shared_dashboard_with_no_filter = Insight.objects.create(
            filters=Filter(
                data={"events": [{"id": "item_cached_because_on_recently_shared_dashboard_with_no_filter"}]}
            ).to_dict(),
            team=self.team,
        )
        tile_to_cache_because_dashboard_was_recently_accessed = DashboardTile.objects.create(
            insight=item_cached_because_on_recently_shared_dashboard_with_no_filter,
            dashboard=recently_accessed_unshared_dashboard_should_cache,
        )

        item_key = generate_cache_key(filter.toJSON() + "_" + str(self.team.pk))
        funnel_key = generate_cache_key(filter.toJSON() + "_" + str(self.team.pk))

        self._run_cache_update(patch_update_cache_item)

        self.assertIsNotNone(Insight.objects.get(pk=cached_insight_because_no_dashboard_filters.pk).last_refresh)
        self.assertIsNotNone(
            DashboardTile.objects.get(pk=cached_trend_tile_because_no_dashboard_filters.pk).last_refresh
        )
        self.assertIsNotNone(Insight.objects.get(pk=cached_funnel_item.pk).last_refresh)
        self.assertIsNotNone(
            DashboardTile.objects.get(pk=cached_funnel_tile_because_on_shared_dashboard.pk).last_refresh
        )

        # dashboard has filters so insight is filters_hash is different and so it doesn't need caching
        self.assertIsNone(Insight.objects.get(pk=insight_not_cached_because_dashboard_has_filters.pk).last_refresh)
        self.assertIsNotNone(DashboardTile.objects.get(pk=tile_cached_because_dashboard_is_shared.pk).last_refresh)

        self.assertIsNone(
            Insight.objects.get(
                pk=insight_not_cached_because_dashboard_unshared_and_not_recently_accessed.pk
            ).last_refresh
        )
        self.assertIsNone(
            DashboardTile.objects.get(pk=tile_to_not_cache_because_dashboard_is_access_too_long_ago.pk).last_refresh
        )

        self.assertIsNotNone(
            Insight.objects.get(pk=item_cached_because_on_recently_shared_dashboard_with_no_filter.pk).last_refresh
        )
        self.assertIsNotNone(
            DashboardTile.objects.get(pk=tile_to_cache_because_dashboard_was_recently_accessed.pk).last_refresh
        )

        self.assertEqual(get_safe_cache(item_key)["result"][0]["count"], 0)
        self.assertEqual(get_safe_cache(funnel_key)["result"][0]["count"], 0)

    @patch("posthog.tasks.update_cache.group.apply_async")
    @patch("posthog.celery.update_cache_item_task.s")
    def test_refresh_dashboard_cache_types(
        self, patch_update_cache_item: MagicMock, _patch_apply_async: MagicMock
    ) -> None:

        self._test_refresh_dashboard_cache_types(
            RetentionFilter(
                data={"insight": "RETENTION", "events": [{"id": "cache this"}], "date_to": now().isoformat()}
            ),
            CacheType.RETENTION,
            patch_update_cache_item,
        )

        self._test_refresh_dashboard_cache_types(
            Filter(data={"insight": "TRENDS", "events": [{"id": "$pageview"}]}),
            CacheType.TRENDS,
            patch_update_cache_item,
        )

        self._test_refresh_dashboard_cache_types(
            StickinessFilter(
                data={
                    "insight": "TRENDS",
                    "shown_as": "Stickiness",
                    "date_from": "2020-01-01",
                    "events": [{"id": "watched movie"}],
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "watched movie",
                },
                team=self.team,
                get_earliest_timestamp=get_earliest_timestamp,
            ),
            CacheType.STICKINESS,
            patch_update_cache_item,
        )

    @freeze_time("2012-01-15")
    def test_update_cache_item_calls_right_class(self) -> None:
        filter = Filter(data={"insight": "TRENDS", "events": [{"id": "$pageview"}]})
        insight, _ = self._create_dashboard(filter)

        update_cache_item(
            generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
            CacheType.TRENDS,
            {"filter": filter.toJSON(), "team_id": self.team.pk,},
        )

        updated_dashboard_item = Insight.objects.get(pk=insight.pk)
        self.assertEqual(updated_dashboard_item.refreshing, False)
        self.assertEqual(updated_dashboard_item.last_refresh, now())

    @freeze_time("2012-01-15")
    @patch("posthog.queries.funnels.ClickhouseFunnelUnordered", create=True)
    @patch("posthog.queries.funnels.ClickhouseFunnelStrict", create=True)
    @patch("posthog.tasks.update_cache.ClickhouseFunnelTimeToConvert", create=True)
    @patch("posthog.tasks.update_cache.ClickhouseFunnelTrends", create=True)
    @patch("posthog.queries.funnels.ClickhouseFunnel", create=True)
    def test_update_cache_item_calls_right_funnel_class_clickhouse(
        self,
        funnel_mock: MagicMock,
        funnel_trends_mock: MagicMock,
        funnel_time_to_convert_mock: MagicMock,
        funnel_strict_mock: MagicMock,
        funnel_unordered_mock: MagicMock,
    ) -> None:
        #  basic funnel
        base_filter = Filter(
            data={
                "insight": "FUNNELS",
                "events": [
                    {"id": "$pageview", "order": 0, "type": "events"},
                    {"id": "$pageview", "order": 1, "type": "events"},
                ],
            }
        )
        dashboard = create_shared_dashboard(is_shared=True, team=self.team)
        insight = Insight.objects.create(name="to be found by filter", team=self.team, filters=base_filter.to_dict())
        DashboardTile.objects.create(insight=insight, dashboard=dashboard)

        filter = base_filter
        funnel_mock.return_value.run.return_value = {}
        update_cache_item(
            generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
            CacheType.FUNNEL,
            {"filter": filter.toJSON(), "team_id": self.team.pk,},
        )
        self.assertEqual(funnel_mock.call_count, 2)  # once for Insight check, once for dashboard tile check

        # trends funnel
        filter = base_filter.with_data({"funnel_viz_type": "trends"})
        insight.filters = filter.to_dict()
        insight.save()
        funnel_trends_mock.return_value.run.return_value = {}
        update_cache_item(
            generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
            CacheType.FUNNEL,
            {"filter": filter.toJSON(), "team_id": self.team.pk,},
        )
        self.assertEqual(funnel_trends_mock.call_count, 2)

        # time to convert funnel
        filter = base_filter.with_data({"funnel_viz_type": "time_to_convert", "funnel_order_type": "strict"})
        insight.filters = filter.to_dict()
        insight.save()
        funnel_time_to_convert_mock.return_value.run.return_value = {}
        update_cache_item(
            generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
            CacheType.FUNNEL,
            {"filter": filter.toJSON(), "team_id": self.team.pk,},
        )
        self.assertEqual(funnel_time_to_convert_mock.call_count, 2)

        # strict funnel
        filter = base_filter.with_data({"funnel_order_type": "strict"})
        insight.filters = filter.to_dict()
        insight.save()
        funnel_strict_mock.return_value.run.return_value = {}
        update_cache_item(
            generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
            CacheType.FUNNEL,
            {"filter": filter.toJSON(), "team_id": self.team.pk,},
        )
        self.assertEqual(funnel_strict_mock.call_count, 2)

        # unordered funnel
        filter = base_filter.with_data({"funnel_order_type": "unordered"})
        insight.filters = filter.to_dict()
        insight.save()
        funnel_unordered_mock.return_value.run.return_value = {}
        update_cache_item(
            generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
            CacheType.FUNNEL,
            {"filter": filter.toJSON(), "team_id": self.team.pk,},
        )
        self.assertEqual(funnel_unordered_mock.call_count, 2)

    def _test_refresh_dashboard_cache_types(
        self, filter: FilterType, cache_type: CacheType, patch_update_cache_item: MagicMock,
    ) -> None:
        insight, dashboard = self._create_dashboard(filter)

        update_cached_items()

        expected_args = [
            generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
            cache_type,
            {
                "filter": filter.toJSON(),
                "team_id": self.team.pk,
                "insight_id": insight.id,
                "dashboard_id": dashboard.id,
            },
        ]

        patch_update_cache_item.assert_any_call(*expected_args)

        update_cache_item(*expected_args)

        item_key = generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk))
        self.assertIsNotNone(get_safe_cache(item_key))

    def _create_dashboard(self, filter: FilterType) -> Tuple[Insight, Dashboard]:
        dashboard_to_cache = create_shared_dashboard(team=self.team, is_shared=True, last_accessed_at=now())

        insight = Insight.objects.create(
            filters=filter.to_dict(), team=self.team, last_refresh=now() - timedelta(days=30),
        )
        DashboardTile.objects.create(insight=insight, dashboard=dashboard_to_cache)
        return insight, dashboard_to_cache

    @patch("posthog.tasks.update_cache.group.apply_async")
    @patch("posthog.celery.update_cache_item_task.s")
    @freeze_time("2012-01-15")
    def test_stickiness_regression(self, patch_update_cache_item: MagicMock, _patch_apply_async: MagicMock) -> None:
        # We moved Stickiness from being a "shown_as" item to its own insight
        # This move caused issues hence a regression test
        filter_stickiness = StickinessFilter(
            data={
                "events": [{"id": "$pageview"}],
                "properties": [{"key": "$browser", "value": "Mac OS X"}],
                "date_from": "2012-01-10",
                "date_to": "2012-01-15",
                "insight": INSIGHT_STICKINESS,
                "shown_as": "Stickiness",
            },
            team=self.team,
            get_earliest_timestamp=get_earliest_timestamp,
        )
        filter = Filter(
            data={
                "events": [{"id": "$pageview"}],
                "properties": [{"key": "$browser", "value": "Mac OS X"}],
                "date_from": "2012-01-10",
                "date_to": "2012-01-15",
            }
        )
        shared_dashboard = create_shared_dashboard(team=self.team, is_shared=True)

        insight = Insight.objects.create(filters=filter_stickiness.to_dict(), team=self.team)
        DashboardTile.objects.create(insight=insight, dashboard=shared_dashboard)
        insight = Insight.objects.create(filters=filter.to_dict(), team=self.team)
        DashboardTile.objects.create(insight=insight, dashboard=shared_dashboard)
        item_stickiness_key = generate_cache_key(filter_stickiness.toJSON() + "_" + str(self.team.pk))
        item_key = generate_cache_key(filter.toJSON() + "_" + str(self.team.pk))

        self._run_cache_update(patch_update_cache_item)

        self.assertEqual(
            get_safe_cache(item_stickiness_key)["result"][0]["labels"],
            ["1 day", "2 days", "3 days", "4 days", "5 days", "6 days"],
        )
        self.assertEqual(
            get_safe_cache(item_key)["result"][0]["labels"],
            ["10-Jan-2012", "11-Jan-2012", "12-Jan-2012", "13-Jan-2012", "14-Jan-2012", "15-Jan-2012",],
        )

    @patch("posthog.tasks.update_cache._calculate_by_filter")
    def test_errors_refreshing(self, patch_calculate_by_filter: MagicMock) -> None:
        """
        When there are no filters on the dashboard the tile and insight cache key match
        the cache only updates cache counts on the Insight not the dashboard tile
        """
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            dashboard_to_cache = create_shared_dashboard(team=self.team, is_shared=True, last_accessed_at=now())
            item_to_cache = Insight.objects.create(
                filters=Filter(
                    data={"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],}
                ).to_dict(),
                team=self.team,
            )
            DashboardTile.objects.create(insight=item_to_cache, dashboard=dashboard_to_cache)

            patch_calculate_by_filter.side_effect = Exception()

            def _update_cached_items() -> None:
                # This function will throw an exception every time which is what we want in production
                try:
                    update_cached_items()
                except Exception:
                    pass

            _update_cached_items()
            self.assertEqual(Insight.objects.get().refresh_attempt, 1)
            self.assertEqual(DashboardTile.objects.get().refresh_attempt, None)
            _update_cached_items()
            self.assertEqual(Insight.objects.get().refresh_attempt, 2)
            self.assertEqual(DashboardTile.objects.get().refresh_attempt, None)

            # Magically succeeds, reset counter
            patch_calculate_by_filter.side_effect = None
            patch_calculate_by_filter.return_value = {"some": "exciting results"}
            _update_cached_items()
            self.assertEqual(Insight.objects.get().refresh_attempt, 0)
            self.assertEqual(DashboardTile.objects.get().refresh_attempt, 0)

            # tick forwards since we ignore recently refreshed tiles
            frozen_datetime.tick(timedelta(minutes=4))

            # We should retry a max of 3 times
            patch_calculate_by_filter.reset_mock()
            patch_calculate_by_filter.side_effect = Exception()
            _update_cached_items()
            _update_cached_items()
            _update_cached_items()
            _update_cached_items()
            self.assertEqual(Insight.objects.get().refresh_attempt, 3)
            self.assertEqual(DashboardTile.objects.get().refresh_attempt, 0)
            self.assertEqual(patch_calculate_by_filter.call_count, 3)

            # If a user later comes back and manually refreshes we should reset refresh_attempt
            patch_calculate_by_filter.side_effect = None
            self.client.get(f"/api/projects/{self.team.pk}/insights/{item_to_cache.pk}/?refresh=true")
            self.assertEqual(Insight.objects.get().refresh_attempt, 0)
            self.assertEqual(DashboardTile.objects.get().refresh_attempt, 0)

    @patch("posthog.tasks.update_cache._calculate_by_filter")
    def test_errors_refreshing_dashboard_tile(self, patch_calculate_by_filter: MagicMock) -> None:
        """
        When a filters_hash matches the dashboard tile and not the insight the cache update doesn't touch the Insight
        but does touch the tile
        """
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            dashboard_to_cache = create_shared_dashboard(
                team=self.team, is_shared=True, last_accessed_at=now(), filters={"date_from": "-14d"}
            )
            item_to_cache = Insight.objects.create(
                filters=Filter(
                    data={"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],}
                ).to_dict(),
                team=self.team,
            )
            DashboardTile.objects.create(insight=item_to_cache, dashboard=dashboard_to_cache)

            patch_calculate_by_filter.side_effect = Exception()

            def _update_cached_items() -> None:
                # This function will throw an exception every time which is what we want in production
                try:
                    update_cached_items()
                except Exception:
                    pass

            _update_cached_items()
            self.assertEqual(Insight.objects.get().refresh_attempt, None)
            self.assertEqual(DashboardTile.objects.get().refresh_attempt, 1)
            _update_cached_items()
            self.assertEqual(Insight.objects.get().refresh_attempt, None)
            self.assertEqual(DashboardTile.objects.get().refresh_attempt, 2)

            # Magically succeeds, reset counter
            patch_calculate_by_filter.side_effect = None
            patch_calculate_by_filter.return_value = {"some": "exciting results"}
            _update_cached_items()
            self.assertEqual(Insight.objects.get().refresh_attempt, None)
            self.assertEqual(DashboardTile.objects.get().refresh_attempt, 0)

            # tick forwards since we ignore recently refreshed tiles
            frozen_datetime.tick(timedelta(minutes=4))
            # We should retry a max of 3 times
            patch_calculate_by_filter.reset_mock()
            patch_calculate_by_filter.side_effect = Exception()
            _update_cached_items()
            _update_cached_items()
            _update_cached_items()
            _update_cached_items()
            self.assertEqual(Insight.objects.get().refresh_attempt, None)
            self.assertEqual(patch_calculate_by_filter.call_count, 3)
            self.assertEqual(DashboardTile.objects.get().refresh_attempt, 3)

            # If a user later comes back and manually refreshes we should reset refresh_attempt
            patch_calculate_by_filter.side_effect = None
            self.client.get(
                f"/api/projects/{self.team.pk}/insights/{item_to_cache.pk}/?refresh=true&from_dashboard={dashboard_to_cache.id}"
            )
            self.assertEqual(Insight.objects.get().refresh_attempt, None)
            self.assertEqual(DashboardTile.objects.get().refresh_attempt, 0)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_filters_multiple_dashboard(self) -> None:
        # Regression test. Previously if we had insights with the same filter, but different dashboard filters, we would only update one of those
        dashboard_14_days: Dashboard = create_shared_dashboard(
            filters={"date_from": "-14d"}, team=self.team, is_shared=True
        )
        dashboard_30_days: Dashboard = create_shared_dashboard(
            filters={"date_from": "-30d"}, team=self.team, is_shared=True
        )
        dashboard_no_filter: Dashboard = create_shared_dashboard(team=self.team, is_shared=True)

        filter = {"events": [{"id": "$pageview"}]}
        filters_hash_with_no_dashboard = generate_cache_key(
            "{}_{}".format(get_filter(data=filter, team=self.team).toJSON(), self.team.id)
        )

        item1 = Insight.objects.create(filters=filter, team=self.team)
        self.assertEqual(item1.filters_hash, filters_hash_with_no_dashboard)

        DashboardTile.objects.create(insight=item1, dashboard=dashboard_14_days)

        # link another insight to a dashboard with a filter
        item2 = Insight.objects.create(filters=filter, team=self.team)
        DashboardTile.objects.create(insight=item2, dashboard=dashboard_30_days)
        dashboard_30_days.save()

        # link an insight to a dashboard with no filters
        item3 = Insight.objects.create(filters=filter, team=self.team)
        DashboardTile.objects.create(insight=item3, dashboard=dashboard_no_filter)
        dashboard_no_filter.save()

        update_cached_items()

        self._assert_number_of_days_in_results(
            DashboardTile.objects.get(insight=item1, dashboard=dashboard_14_days), number_of_days_in_results=15
        )

        self._assert_number_of_days_in_results(
            DashboardTile.objects.get(insight=item2, dashboard=dashboard_30_days), number_of_days_in_results=31
        )
        self._assert_number_of_days_in_results(
            DashboardTile.objects.get(insight=item3, dashboard=dashboard_no_filter), number_of_days_in_results=8
        )

        self.assertEqual(
            Insight.objects.all().order_by("id")[0].last_refresh.isoformat(), "2021-08-25T22:09:14.252000+00:00"
        )
        self.assertEqual(
            Insight.objects.all().order_by("id")[1].last_refresh.isoformat(), "2021-08-25T22:09:14.252000+00:00"
        )
        self.assertEqual(
            Insight.objects.all().order_by("id")[2].last_refresh.isoformat(), "2021-08-25T22:09:14.252000+00:00"
        )

    def _assert_number_of_days_in_results(self, dashboard_tile: DashboardTile, number_of_days_in_results: int) -> None:
        cache_result = get_safe_cache(dashboard_tile.filters_hash)
        number_of_results = len(cache_result["result"][0]["data"])
        self.assertEqual(number_of_results, number_of_days_in_results)

    @freeze_time("2021-08-25T22:09:14.252Z")
    @patch("posthog.tasks.update_cache.insight_update_task_params")
    def test_broken_insights(self, dashboard_item_update_task_params: MagicMock) -> None:
        # sometimes we have broken insights, add a test to catch
        dashboard = create_shared_dashboard(team=self.team, is_shared=True)
        item = Insight.objects.create(filters={}, team=self.team)
        DashboardTile.objects.create(insight=item, dashboard=dashboard)

        update_cached_items()

        self.assertEqual(dashboard_item_update_task_params.call_count, 0)

    @patch("posthog.tasks.update_cache.insight_update_task_params")
    def test_broken_exception_insights(self, dashboard_item_update_task_params: MagicMock) -> None:
        dashboard_item_update_task_params.side_effect = Exception()
        dashboard = create_shared_dashboard(team=self.team, is_shared=True)
        filter = {"events": [{"id": "$pageview"}]}
        item = Insight.objects.create(filters=filter, team=self.team)
        DashboardTile.objects.create(insight=item, dashboard=dashboard)

        update_cached_items()

        self.assertEquals(Insight.objects.get().refresh_attempt, 1)

    @patch("posthog.tasks.update_cache.group.apply_async")
    @patch("posthog.celery.update_cache_item_task.s")
    @freeze_time("2022-01-03T00:00:00.000Z")
    def test_refresh_insight_cache(self, patch_update_cache_item: MagicMock, _patch_apply_async: MagicMock) -> None:
        filter_dict: Dict[str, Any] = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        shared_insight = create_shared_insight(team=self.team, is_shared=True, filters=filter_dict)
        shared_insight_without_filters = create_shared_insight(team=self.team, is_shared=True, filters={})
        shared_insight_deleted = create_shared_insight(team=self.team, is_shared=True, deleted=True)
        shared_insight_refreshing = create_shared_insight(team=self.team, is_shared=True, refreshing=True)

        # Valid insights within the PARALLEL_INSIGHT_CACHE count
        other_insights_in_range = [
            create_shared_insight(
                team=self.team,
                is_shared=True,
                filters=filter_dict,
                last_refresh=datetime(2022, 1, 1).replace(tzinfo=pytz.utc),
            )
            for _ in range(PARALLEL_INSIGHT_CACHE - 1)
        ]

        # Valid insights outside of the PARALLEL_INSIGHT_CACHE count with later refresh date to ensure order
        other_insights_out_of_range = [
            create_shared_insight(
                team=self.team,
                is_shared=True,
                filters=filter_dict,
                last_refresh=datetime(2022, 1, 2).replace(tzinfo=pytz.utc),
            )
            for i in range(5)
        ]

        tasks, queue_length = update_cached_items()

        assert tasks == 5
        assert queue_length == PARALLEL_INSIGHT_CACHE + 5

        for call_item in patch_update_cache_item.call_args_list:
            update_cache_item(*call_item[0])

        assert Insight.objects.get(pk=shared_insight.pk).last_refresh
        assert not Insight.objects.get(pk=shared_insight_without_filters.pk).last_refresh
        assert not Insight.objects.get(pk=shared_insight_deleted.pk).last_refresh
        assert not Insight.objects.get(pk=shared_insight_refreshing.pk).last_refresh

        for insight in other_insights_in_range:
            assert Insight.objects.get(pk=insight.pk).last_refresh == now()
        for insight in other_insights_out_of_range:
            assert not Insight.objects.get(pk=insight.pk).last_refresh == datetime(2022, 1, 2).replace(tzinfo=pytz.utc)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_cache_key_that_matches_no_assets_still_counts_as_a_refresh_attempt_for_dashboard_tiles(self) -> None:
        test_hash = "märg koer lamab parimal tekil"
        insight = _create_insight_with_known_cache_key(self.team, test_hash)
        dashboard, tile = _create_dashboard_tile_with_known_cache_key(
            self.team, insight, test_hash, dashboard_filters={"date_from": "-30d"}
        )

        assert insight.refresh_attempt is None
        assert tile.refresh_attempt is None

        filter_dict: Dict[str, Any] = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        update_cache_item(
            key="a key that does not match",
            cache_type=CacheType.TRENDS,
            payload={
                "filter": Filter(data=filter_dict).toJSON(),
                "team_id": self.team.id,
                "insight_id": insight.id,
                "dashboard_id": dashboard.id,
            },
        )

        insight.refresh_from_db()
        tile.refresh_from_db()
        assert insight.refresh_attempt is None
        assert tile.refresh_attempt == 1

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_cache_key_that_matches_no_assets_still_counts_as_a_refresh_attempt_for_insights(self) -> None:
        test_hash = "märg koer lamab parimal tekil"
        insight = _create_insight_with_known_cache_key(self.team, test_hash)

        assert insight.refresh_attempt is None

        filter_dict: Dict[str, Any] = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        update_cache_item(
            key="a key that does not match",
            cache_type=CacheType.TRENDS,
            payload={
                "filter": Filter(data=filter_dict).toJSON(),
                "team_id": self.team.id,
                "insight_id": insight.id,
                "dashboard_id": None,
            },
        )

        insight.refresh_from_db()
        assert insight.refresh_attempt == 1

    @patch("posthog.tasks.update_cache.statsd.gauge")
    def test_never_refreshed_tiles_are_gauged(self, statsd_gauge: MagicMock) -> None:
        dashboard = create_shared_dashboard(team=self.team, is_shared=True)
        filter = {"events": [{"id": "$pageview"}]}
        item = Insight.objects.create(filters=filter, team=self.team)
        tile: DashboardTile = DashboardTile.objects.create(insight=item, dashboard=dashboard)

        assert tile.last_refresh is None

        update_cached_items()

        statsd_gauge.assert_any_call("update_cache_queue.never_refreshed", 1)

    @freeze_time("2022-12-01T13:54:00.000Z")
    @patch("posthog.tasks.update_cache.statsd.gauge")
    def test_refresh_age_of_tiles_is_gauged(self, statsd_gauge: MagicMock) -> None:
        tile_one = _a_dashboard_tile_with_known_last_refresh(self.team, datetime.now(pytz.utc) - timedelta(hours=1))
        tile_two = _a_dashboard_tile_with_known_last_refresh(self.team, datetime.now(pytz.utc) - timedelta(hours=0.5))

        # should not gauge because no last_refresh
        _a_dashboard_tile_with_known_last_refresh(self.team, None)

        update_cached_items()

        statsd_gauge.assert_any_call(
            "update_cache_queue.dashboards_lag",
            3600,
            tags={
                "insight_id": tile_one.insight_id,
                "dashboard_id": tile_one.dashboard_id,
                "cache_key": tile_one.filters_hash,
            },
        )

        statsd_gauge.assert_any_call(
            "update_cache_queue.dashboards_lag",
            1800,
            tags={
                "insight_id": tile_two.insight_id,
                "dashboard_id": tile_two.dashboard_id,
                "cache_key": tile_two.filters_hash,
            },
        )

        # the tile with no last refresh isn't gauged for lag
        lag_calls = [
            x.args[0]
            for x in statsd_gauge.mock_calls
            if len(x.args) > 0 and x.args[0] == "update_cache_queue.dashboards_lag"
        ]
        assert len(lag_calls) == 2

    @patch("posthog.tasks.update_cache._calculate_by_filter", return_value={"not": "None"})
    @patch("posthog.tasks.update_cache.group.apply_async")
    @patch("posthog.celery.update_cache_item_task.s")
    def test_update_skips_items_refreshed_in_last_three_minutes(
        self, patch_update_cache_item: MagicMock, _patch_apply_async: MagicMock, _patch_generate_results: MagicMock
    ) -> None:

        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            # two tiles that share a hash
            # only one on a shared dashboard
            # the dashboard has no filters so both insights and the tile share a hash key
            insight_one = _create_insight_with_known_cache_key(self.team, None)
            insight_two = _create_insight_with_known_cache_key(self.team, None)
            dashboard, tile = _create_dashboard_tile_with_known_cache_key(
                self.team, insight_one, None, last_accessed_at=datetime.now(pytz.utc)
            )

            self._run_cache_update(patch_update_cache_item)

            tile.refresh_from_db()
            insight_one.refresh_from_db()
            insight_two.refresh_from_db()

            assert tile.last_refresh.isoformat() == "2021-08-25T22:09:14.252000+00:00"
            assert insight_one.last_refresh.isoformat() == "2021-08-25T22:09:14.252000+00:00"
            assert insight_two.last_refresh.isoformat() == "2021-08-25T22:09:14.252000+00:00"

            frozen_datetime.tick(delta=timedelta(minutes=1))

            patch_update_cache_item.reset_mock()
            self._run_cache_update(patch_update_cache_item)

            # refresh dates don't change
            tile.refresh_from_db()
            insight_one.refresh_from_db()
            insight_two.refresh_from_db()

            assert tile.last_refresh.isoformat() == "2021-08-25T22:09:14.252000+00:00"
            assert insight_one.last_refresh.isoformat() == "2021-08-25T22:09:14.252000+00:00"
            assert insight_two.last_refresh.isoformat() == "2021-08-25T22:09:14.252000+00:00"

    @patch("posthog.tasks.update_cache.cache.set")
    @patch("posthog.tasks.update_cache._calculate_by_filter")
    @patch("posthog.tasks.update_cache.group.apply_async")
    @patch("posthog.celery.update_cache_item_task.s")
    @patch("posthog.tasks.update_cache.statsd.incr")
    def test_update_insight_cache_reports_on_updating_tiles_with_no_hash(
        self,
        statsd_incr: MagicMock,
        patch_update_cache_item: MagicMock,
        _patch_apply_async: MagicMock,
        _patch_generate_results: MagicMock,
        _patched_cache_set: MagicMock,
    ) -> None:
        tile = _a_dashboard_tile_with_known_last_refresh(self.team, last_refresh_date=None)
        # can't set filters_hash=None on a route that triggers save
        DashboardTile.objects.filter(id=tile.id).update(filters_hash=None)
        tile.refresh_from_db()
        assert tile.filters_hash is None

        self._run_cache_update(patch_update_cache_item)

        statsd_incr.assert_any_call("update_cache_queue.set_missing_filters_hash", 1)

        tile.refresh_from_db()
        assert tile.filters_hash is not None

    @freeze_time("2021-08-25T22:09:14.252Z")
    @patch("posthog.tasks.update_cache._calculate_by_filter", return_value={"not", "an empty result"})
    @patch("posthog.tasks.update_cache.group.apply_async")
    @patch("posthog.celery.update_cache_item_task.s")
    def test_update_insight_filters_hash(
        self, patch_update_cache_item: MagicMock, _patch_apply_async: MagicMock, _patch_generate_results: MagicMock,
    ) -> None:
        test_hash = "rongi rattad ragisevad"
        insight = _create_insight_with_known_cache_key(self.team, test_hash)
        dashboard, tile = _create_dashboard_tile_with_known_cache_key(
            self.team, insight, test_hash, last_accessed_at=datetime.now(pytz.utc) - timedelta(days=1)
        )

        self._run_cache_update(patch_update_cache_item)

        insight.refresh_from_db()
        assert insight.filters_hash != test_hash
        assert insight.last_refresh.isoformat(), "2021-08-25T22:09:14.252000+00:00"

    @freeze_time("2021-08-25T22:09:14.252Z")
    @patch("posthog.tasks.update_cache.cache.set")
    @patch("posthog.tasks.update_cache._calculate_by_filter", return_value={"not": "empty result"})
    @patch("posthog.tasks.update_cache.group.apply_async")
    @patch("posthog.celery.update_cache_item_task.s")
    def test_update_dashboard_tile_updates_tile_and_insight_filters_hash_when_dashboard_has_no_filters(
        self,
        patch_update_cache_item: MagicMock,
        _patch_apply_async: MagicMock,
        _patch_generate_results: MagicMock,
        _patched_cache_set: MagicMock,
    ) -> None:
        test_hash = "rongi rattad ragisevad"
        insight = _create_insight_with_known_cache_key(self.team, test_hash)
        dashboard, tile = _create_dashboard_tile_with_known_cache_key(
            self.team, insight, test_hash, last_accessed_at=datetime.now(pytz.utc) - timedelta(days=1)
        )

        self._run_cache_update(patch_update_cache_item)

        insight.refresh_from_db()
        tile.refresh_from_db()
        assert insight.filters_hash != test_hash
        assert insight.last_refresh.isoformat(), "2021-08-25T22:09:14.252000+00:00"
        assert tile.filters_hash != test_hash
        assert tile.last_refresh.isoformat() == "2021-08-25T22:09:14.252000+00:00"

    @freeze_time("2021-08-25T22:09:14.252Z")
    @patch("posthog.tasks.update_cache.cache.set")
    @patch("posthog.tasks.update_cache._calculate_by_filter", return_value={"not": "empty result"})
    @patch("posthog.tasks.update_cache.group.apply_async")
    @patch("posthog.celery.update_cache_item_task.s")
    def test_update_dashboard_tile_updates_only_tile_when_different_filters(
        self,
        patch_update_cache_item: MagicMock,
        _patch_apply_async: MagicMock,
        _patch_generate_results: MagicMock,
        _patched_cache_set: MagicMock,
    ) -> None:
        test_hash = "rongi rattad ragisevad"
        insight = _create_insight_with_known_cache_key(self.team, test_hash)
        dashboard, tile = _create_dashboard_tile_with_known_cache_key(
            self.team,
            insight,
            test_hash,
            dashboard_filters={"date_from": "-30d"},
            last_accessed_at=datetime.now(pytz.utc) - timedelta(days=1),
        )

        self._run_cache_update(patch_update_cache_item)

        tile.refresh_from_db()
        insight.refresh_from_db()

        assert insight.filters_hash == test_hash
        assert insight.last_refresh is None
        assert tile.filters_hash != test_hash
        assert tile.last_refresh.isoformat() == "2021-08-25T22:09:14.252000+00:00"

    def _run_cache_update(self, patch_update_cache_item: MagicMock) -> None:
        update_cached_items()
        # pass the caught calls straight to the function
        # we do this to skip Redis
        for call_item in patch_update_cache_item.call_args_list:
            update_cache_item(*call_item[0])
