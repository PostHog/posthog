from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.utils.timezone import now
from freezegun import freeze_time

from posthog.constants import ENTITY_ID, ENTITY_TYPE
from posthog.decorators import CacheType
from posthog.models import Dashboard, DashboardItem, Event, Filter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.queries.trends import Trends
from posthog.tasks.update_cache import update_cache_item, update_cached_items
from posthog.test.base import BaseTest
from posthog.types import FilterType
from posthog.utils import generate_cache_key, get_safe_cache


class TestUpdateCache(BaseTest):
    TESTS_API = True

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

        item = DashboardItem.objects.create(dashboard=shared_dashboard, filters=filter.to_dict(), team=self.team)
        funnel_item = DashboardItem.objects.create(
            dashboard=shared_dashboard, filters=funnel_filter.to_dict(), team=self.team
        )

        dashboard_to_cache = Dashboard.objects.create(team=self.team, is_shared=True, last_accessed_at=now())
        item_to_cache = DashboardItem.objects.create(
            dashboard=dashboard_to_cache,
            filters=Filter(data={"events": [{"id": "cache this"}]}).to_dict(),
            team=self.team,
        )

        dashboard_do_not_cache = Dashboard.objects.create(
            team=self.team, is_shared=True, last_accessed_at="2020-01-01T12:00:00Z"
        )
        item_do_not_cache = DashboardItem.objects.create(
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

        self.assertIsNotNone(DashboardItem.objects.get(pk=item.pk).last_refresh)
        self.assertIsNotNone(DashboardItem.objects.get(pk=item_to_cache.pk).last_refresh)
        self.assertIsNotNone(DashboardItem.objects.get(pk=item_do_not_cache.pk).last_refresh)
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
    @patch("posthog.tasks.update_cache.import_from", return_value=Trends)
    def test_update_cache_item_calls_right_class(self, patch_import_from: MagicMock) -> None:
        filter = Filter(data={"insight": "TRENDS", "events": [{"id": "$pageview"}]})
        dashboard_item = self._create_dashboard(filter)

        with self.settings(EE_AVAILABLE=False):
            update_cache_item(
                generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk)),
                CacheType.TRENDS,
                {"filter": filter.toJSON(), "team_id": self.team.pk,},
            )

        patch_import_from.assert_called_once_with("posthog.queries.trends", "Trends")

        updated_dashboard_item = DashboardItem.objects.get(pk=dashboard_item.pk)
        self.assertEqual(updated_dashboard_item.refreshing, False)
        self.assertEqual(updated_dashboard_item.last_refresh, now())

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

    def _create_dashboard(self, filter: FilterType, item_refreshing: bool = False) -> DashboardItem:
        dashboard_to_cache = Dashboard.objects.create(team=self.team, is_shared=True, last_accessed_at=now())

        return DashboardItem.objects.create(
            dashboard=dashboard_to_cache,
            filters=filter.to_dict(),
            team=self.team,
            last_refresh=now() - timedelta(days=30),
        )
