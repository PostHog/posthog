import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from parameterized import parameterized

from posthog.hogql_queries.query_metadata import extract_query_metadata

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

    @pytest.mark.timeout(60)
    def test_dry_run_finishes_and_changes_nothing(self):
        insights = [self._create_insight_with_legacy_metadata() for _ in range(3)]

        call_command(
            "backfill_insights_query_metadata", team_id=self.team.pk, sleep_interval=0, batch_size=1, dry_run=True
        )

        for insight in insights:
            insight.refresh_from_db()
            assert insight.query_metadata == {"events": ["$pageview"], "updated_at": "2025-01-01T00:00:00Z"}

    def test_failed_extraction_keeps_existing_events(self):
        insight = self._create_insight_with_legacy_metadata()

        with patch("posthog.hogql_queries.query_metadata.extract_query_metadata", side_effect=ValueError("boom")):
            call_command("backfill_insights_query_metadata", team_id=self.team.pk, sleep_interval=0)

        insight.refresh_from_db()
        assert insight.query_metadata is not None
        assert insight.query_metadata["events"] == ["$pageview"]
        assert insight.query_metadata["properties"] == []

    @parameterized.expand(
        [
            ("saved_metadata", {"query_metadata": {"events": ["$identify"], "properties": []}}),
            ("changed_query", {"query": {"kind": "HogQLQuery", "query": "select 1"}}),
        ]
    )
    def test_save_during_extraction_is_not_overwritten(self, _name: str, concurrent_change: dict) -> None:
        insight = self._create_insight_with_legacy_metadata()

        def save_while_extracting(*args, **kwargs):
            Insight.objects_including_soft_deleted.filter(pk=insight.pk).update(**concurrent_change)
            return extract_query_metadata(*args, **kwargs)

        with patch("posthog.hogql_queries.query_metadata.extract_query_metadata", side_effect=save_while_extracting):
            call_command("backfill_insights_query_metadata", team_id=self.team.pk, sleep_interval=0)

        insight.refresh_from_db()
        for field, value in concurrent_change.items():
            assert getattr(insight, field) == value
        if "query_metadata" not in concurrent_change:
            assert insight.query_metadata == {"events": ["$pageview"], "updated_at": "2025-01-01T00:00:00Z"}
