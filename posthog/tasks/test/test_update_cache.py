from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.utils.timezone import now
from freezegun import freeze_time

from posthog.constants import ENTITY_ID, ENTITY_TYPE, INSIGHT_STICKINESS
from posthog.decorators import CacheType
from posthog.models import Dashboard, Event, Filter, Insight
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.queries.trends import Trends
from posthog.tasks.update_cache import update_cache_item, update_cached_items
from posthog.test.base import APIBaseTest
from posthog.types import FilterType
from posthog.utils import generate_cache_key, get_safe_cache


class TestUpdateCache(APIBaseTest):
    @patch("posthog.tasks.update_cache.group.apply_async")
    @patch("posthog.celery.update_cache_item_task.s")
    def test_refresh_dashboard_cache(self, patch_update_cache_item: MagicMock, patch_apply_async: MagicMock) -> None:
        # There's two things we want to refresh
        # Any shared dashboard, as we only use cached items to show those
        # Any dashboard accessed in the last 7 days
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }
        filter = Filter(data=filter_dict)
        shared_dashboard = Dashboard.objects.create(team=self.team, is_shared=True)
        funnel_filter = Filter(data={"events": [{"id": "user signed up", "type": "events", "order": 0},],})

        item = Insight.objects.create(dashboard=shared_dashboard, filters=filter.to_dict(), team=self.team)
        funnel_item = Insight.objects.create(
            dashboard=shared_dashboard, filters=funnel_filter.to_dict(), team=self.team
        )

        dashboard_to_cache = Dashboard.objects.create(team=self.team, is_shared=True, last_accessed_at=now())
        item_to_cache = Insight.objects.create(
            dashboard=dashboard_to_cache,
            filters=Filter(data={"events": [{"id": "cache this"}]}).to_dict(),
            team=self.team,
        )

        dashboard_do_not_cache = Dashboard.objects.create(
            team=self.team, is_shared=True, last_accessed_at="2020-01-01T12:00:00Z"
        )
        item_do_not_cache = Insight.objects.create(
            dashboard=dashboard_do_not_cache,
            filters=Filter(data={"events": [{"id": "do not cache this"}]}).to_dict(),
            team=self.team,
        )

        item_key = generate_cache_key(filter.toJSON() + "_" + str(self.team.pk))
        funnel_key = generate_cache_key(filter.toJSON() + "_" + str(self.team.pk))
        update_cached_items()

        # pass the caught calls straight to the function
        # we do this to skip Redis
        for call_item in patch_update_cache_item.call_args_list:
            update_cache_item(*call_item[0])

        self.assertIsNotNone(Insight.objects.get(pk=item.pk).last_refresh)
        self.assertIsNotNone(Insight.objects.get(pk=item_to_cache.pk).last_refresh)
        self.assertIsNotNone(Insight.objects.get(pk=item_do_not_cache.pk).last_refresh)
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
                get_earliest_timestamp=Event.objects.earliest_timestamp,
            ),
            CacheType.STICKINESS,
            patch_update_cache_item,
        )

    @freeze_time("2012-01-15")
    def test_update_cache_item_calls_right_class(self) -> None:
        filter = Filter(data={"insight": "TRENDS", "events": [{"id": "$pageview"}]})
        dashboard_item = self._create_dashboard(filter)

        with self.settings(EE_AVAILABLE=False):
            update_cache_item(
                generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
                CacheType.TRENDS,
                {"filter": filter.toJSON(), "team_id": self.team.pk,},
            )

        updated_dashboard_item = Insight.objects.get(pk=dashboard_item.pk)
        self.assertEqual(updated_dashboard_item.refreshing, False)
        self.assertEqual(updated_dashboard_item.last_refresh, now())

    @freeze_time("2012-01-15")
    @patch("posthog.tasks.update_cache.Funnel")
    def test_update_cache_item_calls_right_funnel_class(self, funnel_mock: MagicMock) -> None:
        #  basic funnel
        filter = Filter(
            data={
                "insight": "FUNNELS",
                "events": [
                    {"id": "$pageview", "order": 0, "type": "events"},
                    {"id": "$pageview", "order": 1, "type": "events"},
                ],
            }
        )
        dashboard_item = self._create_dashboard(filter)

        funnel_mock.return_value.run.return_value = {}
        with self.settings(EE_AVAILABLE=False):
            update_cache_item(
                generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
                CacheType.FUNNEL,
                {"filter": filter.toJSON(), "team_id": self.team.pk,},
            )

        updated_dashboard_item = Insight.objects.get(pk=dashboard_item.pk)
        self.assertEqual(updated_dashboard_item.refreshing, False)
        self.assertEqual(updated_dashboard_item.last_refresh, now())
        funnel_mock.assert_called_once()

    @freeze_time("2012-01-15")
    @patch("posthog.tasks.update_cache.ClickhouseFunnelUnordered", create=True)
    @patch("posthog.tasks.update_cache.ClickhouseFunnelStrict", create=True)
    @patch("posthog.tasks.update_cache.ClickhouseFunnelTimeToConvert", create=True)
    @patch("posthog.tasks.update_cache.ClickhouseFunnelTrends", create=True)
    @patch("posthog.tasks.update_cache.ClickhouseFunnel", create=True)
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

        with self.settings(EE_AVAILABLE=True, PRIMARY_DB="clickhouse"):
            filter = base_filter
            funnel_mock.return_value.run.return_value = {}
            update_cache_item(
                generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
                CacheType.FUNNEL,
                {"filter": filter.toJSON(), "team_id": self.team.pk,},
            )
            funnel_mock.assert_called_once()

            # trends funnel
            filter = base_filter.with_data({"funnel_viz_type": "trends"})
            funnel_trends_mock.return_value.run.return_value = {}
            update_cache_item(
                generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
                CacheType.FUNNEL,
                {"filter": filter.toJSON(), "team_id": self.team.pk,},
            )

            funnel_trends_mock.assert_called_once()
            self.assertEqual(funnel_trends_mock.call_args[1]["funnel_order_class"], funnel_mock)
            funnel_trends_mock.reset_mock()

            # trends unordered funnel
            filter = base_filter.with_data({"funnel_viz_type": "trends", "funnel_order_type": "unordered"})
            funnel_trends_mock.return_value.run.return_value = {}
            update_cache_item(
                generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
                CacheType.FUNNEL,
                {"filter": filter.toJSON(), "team_id": self.team.pk,},
            )

            funnel_trends_mock.assert_called_once()
            self.assertEqual(funnel_trends_mock.call_args[1]["funnel_order_class"], funnel_unordered_mock)
            funnel_trends_mock.reset_mock()

            # time to convert strict funnel
            filter = base_filter.with_data({"funnel_viz_type": "time_to_convert", "funnel_order_type": "strict"})
            funnel_time_to_convert_mock.return_value.run.return_value = {}
            update_cache_item(
                generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
                CacheType.FUNNEL,
                {"filter": filter.toJSON(), "team_id": self.team.pk,},
            )

            funnel_time_to_convert_mock.assert_called_once()
            self.assertEqual(funnel_time_to_convert_mock.call_args[1]["funnel_order_class"], funnel_strict_mock)
            funnel_time_to_convert_mock.reset_mock()

            # strict funnel
            filter = base_filter.with_data({"funnel_order_type": "strict"})
            funnel_strict_mock.return_value.run.return_value = {}
            update_cache_item(
                generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
                CacheType.FUNNEL,
                {"filter": filter.toJSON(), "team_id": self.team.pk,},
            )

            funnel_strict_mock.assert_called_once()

    def _test_refresh_dashboard_cache_types(
        self, filter: FilterType, cache_type: CacheType, patch_update_cache_item: MagicMock,
    ) -> None:
        self._create_dashboard(filter)

        update_cached_items()

        expected_args = [
            generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
            cache_type,
            {"filter": filter.toJSON(), "team_id": self.team.pk,},
        ]

        patch_update_cache_item.assert_any_call(*expected_args)

        update_cache_item(*expected_args)  # type: ignore

        item_key = generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk))
        self.assertIsNotNone(get_safe_cache(item_key))

    def _create_dashboard(self, filter: FilterType, item_refreshing: bool = False) -> Insight:
        dashboard_to_cache = Dashboard.objects.create(team=self.team, is_shared=True, last_accessed_at=now())

        return Insight.objects.create(
            dashboard=dashboard_to_cache,
            filters=filter.to_dict(),
            team=self.team,
            last_refresh=now() - timedelta(days=30),
        )

    @patch("posthog.tasks.update_cache.group.apply_async")
    @patch("posthog.celery.update_cache_item_task.s")
    @freeze_time("2012-01-15")
    def test_stickiness_regression(self, patch_update_cache_item: MagicMock, patch_apply_async: MagicMock) -> None:
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
            get_earliest_timestamp=Event.objects.earliest_timestamp,
        )
        filter = Filter(
            data={
                "events": [{"id": "$pageview"}],
                "properties": [{"key": "$browser", "value": "Mac OS X"}],
                "date_from": "2012-01-10",
                "date_to": "2012-01-15",
            }
        )
        shared_dashboard = Dashboard.objects.create(team=self.team, is_shared=True)

        Insight.objects.create(dashboard=shared_dashboard, filters=filter_stickiness.to_dict(), team=self.team)
        Insight.objects.create(dashboard=shared_dashboard, filters=filter.to_dict(), team=self.team)

        item_stickiness_key = generate_cache_key(filter_stickiness.toJSON() + "_" + str(self.team.pk))
        item_key = generate_cache_key(filter.toJSON() + "_" + str(self.team.pk))

        update_cached_items()

        for call_item in patch_update_cache_item.call_args_list:
            update_cache_item(*call_item[0])

        self.assertEqual(
            get_safe_cache(item_stickiness_key)["result"][0]["labels"],
            ["1 day", "2 days", "3 days", "4 days", "5 days", "6 days"],
        )
        self.assertEqual(
            get_safe_cache(item_key)["result"][0]["labels"],
            ["10-Jan-2012", "11-Jan-2012", "12-Jan-2012", "13-Jan-2012", "14-Jan-2012", "15-Jan-2012",],
        )
