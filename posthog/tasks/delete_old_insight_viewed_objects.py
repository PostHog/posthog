from django.utils import timezone

from posthog.models import InsightViewed


def delete_old_insight_viewed_objects() -> None:
    """Adds a 30 day TTL to the InsightViewed model."""
    InsightViewed.objects.filter(last_viewed_at__lte=timezone.now() - timezone.timedelta(days=30)).delete()
