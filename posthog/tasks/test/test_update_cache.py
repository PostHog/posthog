from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils.timezone import now

from posthog.models import Dashboard, DashboardItem, Event, Filter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.tasks.update_cache import update_cache_item, update_cached_items
from posthog.test.base import BaseTest
from posthog.types import FilterType
from posthog.utils import generate_cache_key


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
        self.assertEqual(cache.get(item_key)["result"][0]["count"], 0)
        self.assertEqual(cache.get(funnel_key)["result"][0]["count"], 0)

    def _test_refresh_dashboard_cache_types(
        self, filter: FilterType, patch_update_cache_item: MagicMock, patch_apply_async: MagicMock,
    ) -> None:

        dashboard_to_cache = Dashboard.objects.create(team=self.team, is_shared=True, last_accessed_at=now())

        DashboardItem.objects.create(
            dashboard=dashboard_to_cache,
            filters=filter.to_dict(),
            team=self.team,
            last_refresh=now() - timedelta(days=30),
        )
        update_cached_items()

        for call_item in patch_update_cache_item.call_args_list:
            update_cache_item(*call_item[0])

        item_key = generate_cache_key("{}_{}".format(filter.toJSON(), self.team.pk))
        self.assertIsNotNone(cache.get(item_key))

    @patch("posthog.tasks.update_cache.group.apply_async")
    @patch("posthog.celery.update_cache_item_task.s")
    def test_refresh_dashboard_cache_types(
        self, patch_update_cache_item: MagicMock, patch_apply_async: MagicMock
    ) -> None:

        self._test_refresh_dashboard_cache_types(
            RetentionFilter(
                data={"insight": "RETENTION", "events": [{"id": "cache this"}], "date_to": now().isoformat()}
            ),
            patch_update_cache_item,
            patch_apply_async,
        )

        self._test_refresh_dashboard_cache_types(
            Filter(data={"insight": "TRENDS", "events": [{"id": "$pageview"}]}),
            patch_update_cache_item,
            patch_apply_async,
        )

        self._test_refresh_dashboard_cache_types(
            StickinessFilter(
                data={
                    "insight": "TRENDS",
                    "shown_as": "Stickiness",
                    "date_from": "2020-01-01",
                    "events": [{"id": "watched movie"}],
                },
                team=self.team,
                get_earliest_timestamp=Event.objects.earliest_timestamp,
            ),
            patch_update_cache_item,
            patch_apply_async,
        )
