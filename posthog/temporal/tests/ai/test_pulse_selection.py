import pytest

from posthog.temporal.ai.pulse.selection import _select_saved_insight_candidates


@pytest.mark.django_db
class TestSelectSavedInsightCandidates:
    def _insight(self, team, name, kind="TrendsQuery", saved=True, deleted=False):
        from products.product_analytics.backend.models.insight import Insight

        return Insight.objects.create(
            team=team,
            name=name,
            saved=saved,
            deleted=deleted,
            query={"kind": kind, "series": [{"kind": "EventsNode", "event": "x"}]},
        )

    def test_picks_trends_insights_only(self, team):
        self._insight(team, "Weekly signups", "TrendsQuery")
        self._insight(team, "Onboarding funnel", "FunnelsQuery")

        out = _select_saved_insight_candidates(team, limit=10, existing_ids=set())

        labels = [c.descriptor.label for c in out]
        assert "Weekly signups" in labels
        assert "Onboarding funnel" not in labels  # non-Trends dropped
        assert all(c.descriptor.source == "saved_insight" for c in out)

    def test_respects_existing_ids(self, team):
        insight = self._insight(team, "Weekly signups")
        out = _select_saved_insight_candidates(team, limit=10, existing_ids={str(insight.id)})
        assert out == []

    def test_skips_deleted_and_unsaved(self, team):
        self._insight(team, "Deleted", deleted=True)
        self._insight(team, "Unsaved", saved=False)
        assert _select_saved_insight_candidates(team, limit=10, existing_ids=set()) == []
