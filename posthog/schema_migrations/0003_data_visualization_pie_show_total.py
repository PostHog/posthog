from posthog.schema_migrations.base import SchemaMigration


class Migration(SchemaMigration):
    """Move the boolean 'showPieTotal' off ChartSettings into the nested 'pie' settings as 'showTotal'."""

    targets = {"DataVisualizationNode": 1}

    def transform(self, query: dict) -> dict:
        if query["kind"] != "DataVisualizationNode":
            return query

        chart_settings = query.get("chartSettings")
        if not isinstance(chart_settings, dict) or "showPieTotal" not in chart_settings:
            return query

        show_pie_total = chart_settings.pop("showPieTotal")

        pie = chart_settings.setdefault("pie", {})
        # Respect an already-migrated value; only backfill when 'showTotal' is unset.
        pie.setdefault("showTotal", show_pie_total)

        return query
