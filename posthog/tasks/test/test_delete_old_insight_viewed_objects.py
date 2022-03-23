from datetime import timedelta

from django.utils import timezone

from posthog.models import Filter, Insight, InsightViewed
from posthog.tasks.delete_old_insight_viewed_objects import delete_old_insight_viewed_objects
from posthog.test.base import APIBaseTest


class TestDeleteOldInsightViewedObjects(APIBaseTest):
    def test_old_objects_are_deleted_while_newer_ones_kept(self) -> None:
        now = timezone.now()

        filter_dict = {
            "events": [{"id": "$pageview"}],
        }

        insight_1 = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
        )
        InsightViewed.objects.create(
            team=self.team, user=self.user, insight=insight_1, last_viewed_at=now - timedelta(days=31)
        )

        insight_2 = Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="87654321",
        )
        InsightViewed.objects.create(
            team=self.team, user=self.user, insight=insight_2, last_viewed_at=now - timedelta(days=29)
        )

        self.assertEqual(InsightViewed.objects.count(), 2)
        delete_old_insight_viewed_objects()
        self.assertEqual(InsightViewed.objects.count(), 1)
