import pytest
from unittest.mock import patch

from posthog.temporal.ai.pulse.selection import _select_saved_insight_candidates, _select_sync
from posthog.temporal.ai.pulse.types import CandidateMetric, MetricDescriptor, PulseScanConfig

_SELECTION = "posthog.temporal.ai.pulse.selection."


def _candidate(source: str, source_id: str) -> CandidateMetric:
    return CandidateMetric(
        descriptor=MetricDescriptor(source=source, source_id=source_id, label=f"{source}-{source_id}", query={})
    )


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


@pytest.mark.django_db
class TestSelectSyncConfig:
    """_select_sync is database_sync_to_async-wrapped; .func is the raw sync callable we exercise directly.

    The per-source helpers are mocked so only the config-driven orchestration (per-source on/off + the
    overall cap) is under test, not the underlying product-model queries.
    """

    def _patched_sources(self):
        return (
            patch(_SELECTION + "_select_dashboard_tile_candidates", return_value=[_candidate("dashboard_tile", "d1")]),
            patch(
                _SELECTION + "_select_recent_viewed_insight_candidates",
                return_value=[_candidate("recent_insight", "r1")],
            ),
            patch(_SELECTION + "_select_saved_insight_candidates", return_value=[_candidate("saved_insight", "s1")]),
            patch(_SELECTION + "_select_top_event_candidates", return_value=[_candidate("top_event", "e1")]),
        )

    def test_all_sources_contribute_at_defaults(self, team):
        dash, recent, saved, top = self._patched_sources()
        with dash, recent, saved, top:
            out = _select_sync.func(team.id, PulseScanConfig())
        assert {c.descriptor.source for c in out} == {"dashboard_tile", "recent_insight", "saved_insight", "top_event"}

    def test_limit_zero_disables_each_source(self, team):
        dash, recent, saved, top = self._patched_sources()
        with dash as m_dash, recent as m_recent, saved as m_saved, top as m_top:
            config = PulseScanConfig(
                dashboard_tile_limit=0, recent_insight_limit=0, saved_insight_limit=0, top_event_limit=25
            )
            out = _select_sync.func(team.id, config)
        assert {c.descriptor.source for c in out} == {"top_event"}
        m_dash.assert_not_called()
        m_recent.assert_not_called()
        m_saved.assert_not_called()
        m_top.assert_called_once()

    def test_max_candidates_caps_total(self, team):
        dash, recent, saved, top = self._patched_sources()
        with dash, recent, saved, top:
            out = _select_sync.func(team.id, PulseScanConfig(max_candidates=2))
        assert len(out) == 2
