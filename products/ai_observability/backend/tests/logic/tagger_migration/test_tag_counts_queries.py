from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from products.ai_observability.backend.logic.tagger_migration.tag_counts_queries import load_recent_tag_counts


class TestLoadRecentTagCounts(ClickhouseTestMixin, BaseTest):
    def test_counts_recent_tags_of_the_asked_taggers_only(self) -> None:
        now = timezone.now()
        for tagger_id, days_ago in (("active", 1), ("active", 29), ("active", 31), ("other", 2), ("unasked", 1)):
            _create_event(
                team=self.team,
                event="$ai_tag",
                distinct_id="user-1",
                timestamp=now - timedelta(days=days_ago),
                properties={"$ai_tagger_id": tagger_id},
            )
        _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id="user-1",
            timestamp=now,
            properties={"$ai_tagger_id": "active"},
        )
        flush_persons_and_events()

        assert load_recent_tag_counts(self.team, ["active", "other", "silent"]) == {"active": 2, "other": 1}
