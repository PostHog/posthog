from posthog.test.base import BaseTest

from django.core.management import call_command

from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

LEGACY_FILTERS = {"insight": "TRENDS", "events": [{"id": "$pageview", "type": "events", "order": 0}]}
EXISTING_QUERY = {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": []}}


class TestMigrateDashboardTemplateTilesToQuery(BaseTest):
    def test_converts_filters_tiles_and_preserves_modern_ones(self):
        template = DashboardTemplate.objects.create(
            team=self.team,
            template_name="mixed",
            tiles=[
                {"type": "INSIGHT", "name": "legacy", "filters": LEGACY_FILTERS, "layouts": {}},
                {"type": "INSIGHT", "name": "both", "filters": LEGACY_FILTERS, "query": EXISTING_QUERY, "layouts": {}},
                {"type": "TEXT", "body": "hello"},
            ],
        )

        call_command("migrate_dashboard_template_tiles_to_query", "--live")

        template.refresh_from_db()
        assert template.tiles is not None
        legacy_tile, both_tile, text_tile = template.tiles
        assert legacy_tile["query"]["kind"] == "InsightVizNode"
        assert legacy_tile["query"]["source"]["kind"] == "TrendsQuery"
        assert "filters" not in legacy_tile
        # A tile that already has a query keeps it verbatim — conversion must not clobber it.
        assert both_tile["query"] == EXISTING_QUERY
        assert "filters" not in both_tile
        assert text_tile == {"type": "TEXT", "body": "hello"}

    def test_dry_run_by_default_writes_nothing(self):
        template = DashboardTemplate.objects.create(
            team=self.team, template_name="legacy", tiles=[{"type": "INSIGHT", "filters": LEGACY_FILTERS}]
        )

        call_command("migrate_dashboard_template_tiles_to_query")

        template.refresh_from_db()
        assert template.tiles is not None
        assert "filters" in template.tiles[0]
        assert "query" not in template.tiles[0]
