from posthog.celery import update_cache_item
from posthog.api.test.base import BaseTest
from posthog.models import Filter, DashboardItem, Dashboard
from posthog.utils import generate_cache_key
from django.core.cache import cache
from freezegun import freeze_time
import json


class TestUpdateCache(BaseTest):
    TESTS_API = True

    def test_caching_dashboard_items(self) -> None:
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }
        filter = Filter(data=filter_dict)
        dashboard = Dashboard.objects.create(team=self.team)
        item = DashboardItem.objects.create(
            dashboard=dashboard, filters=filter.to_dict(), team=self.team
        )
        item2 = DashboardItem.objects.create(
            dashboard=dashboard, filters=filter.to_dict(), team=self.team
        )
        # create cache
        response = self.client.get(
            "/api/action/trends/?events=%s&properties=%s"
            % (json.dumps(filter_dict["events"]), json.dumps(filter_dict["properties"]))
        )
        self.assertEqual(response.status_code, 200)

        cache_key = generate_cache_key(filter.toJSON() + "_" + str(self.team.pk))

        with freeze_time("2020-01-04T13:00:01Z"):
            cache_item = cache.get(cache_key)
            update_cache_item(
                cache_key, cache_item["type"], cache_item["details"], last_accessed=None
            )

        items = DashboardItem.objects.all()
        self.assertEqual(items[0].last_refresh.isoformat(), "2020-01-04T13:00:01+00:00")
        self.assertEqual(items[1].last_refresh.isoformat(), "2020-01-04T13:00:01+00:00")
