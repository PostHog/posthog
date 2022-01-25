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

        update_cache_item(
            generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
            CacheType.TRENDS,
            {"filter": filter.toJSON(), "team_id": self.team.pk,},
        )

        updated_dashboard_item = Insight.objects.get(pk=dashboard_item.pk)
        self.assertEqual(updated_dashboard_item.refreshing, False)
        self.assertEqual(updated_dashboard_item.last_refresh, now())

    @freeze_time("2012-01-15")
    @patch("ee.clickhouse.queries.funnels.ClickhouseFunnelUnordered", create=True)
    @patch("ee.clickhouse.queries.funnels.ClickhouseFunnelStrict", create=True)
    @patch("posthog.tasks.update_cache.ClickhouseFunnelTimeToConvert", create=True)
    @patch("posthog.tasks.update_cache.ClickhouseFunnelTrends", create=True)
    @patch("ee.clickhouse.queries.funnels.ClickhouseFunnel", create=True)
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

        with self.settings(PRIMARY_DB="clickhouse"):
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

            # time to convert funnel
            filter = base_filter.with_data({"funnel_viz_type": "time_to_convert", "funnel_order_type": "strict"})
            funnel_time_to_convert_mock.return_value.run.return_value = {}
            update_cache_item(
                generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
                CacheType.FUNNEL,
                {"filter": filter.toJSON(), "team_id": self.team.pk,},
            )
            funnel_time_to_convert_mock.assert_called_once()

            # strict funnel
            filter = base_filter.with_data({"funnel_order_type": "strict"})
            funnel_strict_mock.return_value.run.return_value = {}
            update_cache_item(
                generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
                CacheType.FUNNEL,
                {"filter": filter.toJSON(), "team_id": self.team.pk,},
            )
            funnel_strict_mock.assert_called_once()

            # unordered funnel
            filter = base_filter.with_data({"funnel_order_type": "unordered"})
            funnel_unordered_mock.return_value.run.return_value = {}
            update_cache_item(
                generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
                CacheType.FUNNEL,
                {"filter": filter.toJSON(), "team_id": self.team.pk,},
            )
            funnel_unordered_mock.assert_called_once()

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

    @patch("posthog.tasks.update_cache._calculate_by_filter")
    def test_errors_refreshing(self, patch_calculate_by_filter: MagicMock) -> None:
        dashboard_to_cache = Dashboard.objects.create(team=self.team, is_shared=True, last_accessed_at=now())
        item_to_cache = Insight.objects.create(
            dashboard=dashboard_to_cache,
            filters=Filter(
                data={"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],}
            ).to_dict(),
            team=self.team,
        )

        patch_calculate_by_filter.side_effect = Exception()

        def _update_cached_items() -> None:
            # This function will throw an exception every time which is what we want in production
            try:
                update_cached_items()
            except Exception as e:
                pass

        _update_cached_items()
        self.assertEqual(Insight.objects.get().refresh_attempt, 1)
        _update_cached_items()
        self.assertEqual(Insight.objects.get().refresh_attempt, 2)

        # Magically succeeds, reset counter
        patch_calculate_by_filter.side_effect = None
        patch_calculate_by_filter.return_value = {}
        _update_cached_items()
        self.assertEqual(Insight.objects.get().refresh_attempt, 0)

        # We should retry a max of 3 times
        patch_calculate_by_filter.side_effect = Exception()
        _update_cached_items()
        _update_cached_items()
        _update_cached_items()
        _update_cached_items()
        self.assertEqual(Insight.objects.get().refresh_attempt, 3)
        self.assertEqual(patch_calculate_by_filter.call_count, 6)  # ie not 7

        # If a user later comes back and manually refreshes we should reset refresh_attempt
        patch_calculate_by_filter.side_effect = None
        data = self.client.get(f"/api/projects/{self.team.pk}/insights/{item_to_cache.pk}/?refresh=true")
        self.assertEqual(Insight.objects.get().refresh_attempt, 0)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_filters_multiple_dashboard(self) -> None:
        # Regression test. Previously if we had insights with the same filter, but different dashboard filters, we woul donly update one of those
        dashboard1 = Dashboard.objects.create(filters={"date_from": "-14d"}, team=self.team, is_shared=True)
        dashboard2 = Dashboard.objects.create(filters={"date_from": "-30d"}, team=self.team, is_shared=True)
        dashboard3 = Dashboard.objects.create(team=self.team, is_shared=True)

        filter = {"events": [{"id": "$pageview"}]}

        item1 = Insight.objects.create(dashboard=dashboard1, filters=filter, team=self.team)
        item2 = Insight.objects.create(dashboard=dashboard2, filters=filter, team=self.team)
        item3 = Insight.objects.create(dashboard=dashboard3, filters=filter, team=self.team)

        update_cached_items()

        insights = Insight.objects.all().order_by("id")

        self.assertEqual(len(get_safe_cache(insights[0].filters_hash)["result"][0]["data"]), 15)
        self.assertEqual(len(get_safe_cache(insights[1].filters_hash)["result"][0]["data"]), 31)
        self.assertEqual(len(get_safe_cache(insights[2].filters_hash)["result"][0]["data"]), 8)
        self.assertEqual(insights[0].last_refresh.isoformat(), "2021-08-25T22:09:14.252000+00:00")
        self.assertEqual(insights[1].last_refresh.isoformat(), "2021-08-25T22:09:14.252000+00:00")
        self.assertEqual(insights[2].last_refresh.isoformat(), "2021-08-25T22:09:14.252000+00:00")

        # self.assertEquals(insights[0].filters_hash, generate_cache_key('{}_{}'.format(Filter(data=filter).toJSON(), self.team.pk)))
        # self.assertEquals(insights[1].filters_hash, generate_cache_key('{}_{}'.format(Filter(data=filter).toJSON(), self.team.pk)))
        # self.assertEquals(insights[2].filters_hash, generate_cache_key('{}_{}'.format(Filter(data=filter).toJSON(), self.team.pk)))

        # TODO: assert each items cache has the right number of days and the right filters hash

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_insights_old_filter(self) -> None:
        # Some filters hashes are wrong (likely due to changes in our filters models) and previously we would not save changes to those insights and constantly retry them.
        dashboard = Dashboard.objects.create(team=self.team, is_shared=True)
        filter = {"events": [{"id": "$pageview"}]}
        item = Insight.objects.create(
            dashboard=dashboard, filters=filter, filters_hash="cache_thisiswrong", team=self.team
        )
        Insight.objects.all().update(filters_hash="cache_thisiswrong")
        self.assertEquals(Insight.objects.get().filters_hash, "cache_thisiswrong")

        update_cached_items()

        self.assertEquals(
            Insight.objects.get().filters_hash,
            generate_cache_key("{}_{}".format(Filter(data=filter).toJSON(), self.team.pk)),
        )
        self.assertEquals(Insight.objects.get().last_refresh.isoformat(), "2021-08-25T22:09:14.252000+00:00")

    @freeze_time("2021-08-25T22:09:14.252Z")
    @patch("posthog.tasks.update_cache.dashboard_item_update_task_params")
    def test_broken_insights(self, dashboard_item_update_task_params: MagicMock) -> None:
        # sometimes we have broken insights, add a test to catch
        dashboard = Dashboard.objects.create(team=self.team, is_shared=True)
        item = Insight.objects.create(dashboard=dashboard, filters={}, team=self.team)

        update_cached_items()

        self.assertEqual(dashboard_item_update_task_params.call_count, 0)

    @patch("posthog.tasks.update_cache.dashboard_item_update_task_params")
    def test_broken_exception_insights(self, dashboard_item_update_task_params: MagicMock) -> None:
        dashboard_item_update_task_params.side_effect = Exception()
        dashboard = Dashboard.objects.create(team=self.team, is_shared=True)
        filter = {"events": [{"id": "$pageview"}]}
        item = Insight.objects.create(dashboard=dashboard, filters=filter, team=self.team)

        update_cached_items()

        self.assertEquals(Insight.objects.get().refresh_attempt, 1)
