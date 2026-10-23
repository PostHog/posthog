import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command

from products.product_analytics.backend.facade.models import Insight


class TestBackfillInsightsQueryMetadata(BaseTest):
    def _create_insight_with_legacy_metadata(self) -> Insight:
        insight = Insight.objects.create(
            team=self.team,
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "event": "$pageview",
                            "properties": [{"key": "$browser", "type": "event", "value": "Chrome"}],
                        }
                    ],
                },
            },
        )
        # Simulate rows written before metadata carried properties; update() bypasses the save hook
        Insight.objects_including_soft_deleted.filter(pk=insight.pk).update(
            query_metadata={"events": ["$pageview"], "updated_at": "2025-01-01T00:00:00Z"}
        )
        return insight

    def test_regenerates_metadata_without_properties_key(self):
        insight = self._create_insight_with_legacy_metadata()

        call_command("backfill_insights_query_metadata", team_id=self.team.pk, sleep_interval=0)

        insight.refresh_from_db()
        assert insight.query_metadata is not None
        assert insight.query_metadata["events"] == ["$pageview"]
        assert insight.query_metadata["properties"] == [{"type": "event", "name": "$browser"}]

    def test_skips_metadata_that_already_has_properties(self):
        insight = self._create_insight_with_legacy_metadata()
        current_metadata = {"events": ["$pageview"], "properties": [], "updated_at": "2025-01-01T00:00:00Z"}
        Insight.objects_including_soft_deleted.filter(pk=insight.pk).update(query_metadata=current_metadata)

        call_command("backfill_insights_query_metadata", team_id=self.team.pk, sleep_interval=0)

        insight.refresh_from_db()
        assert insight.query_metadata == current_metadata

    @pytest.mark.timeout(60)
    def test_finishes_when_a_queryless_insight_has_legacy_metadata(self):
        insight = self._create_insight_with_legacy_metadata()
        legacy_metadata = {"events": ["$pageview"], "updated_at": "2025-01-01T00:00:00Z"}
        Insight.objects_including_soft_deleted.filter(pk=insight.pk).update(query=None, query_metadata=legacy_metadata)

        call_command("backfill_insights_query_metadata", team_id=self.team.pk, sleep_interval=0)

        insight.refresh_from_db()
        assert insight.query_metadata == legacy_metadata
