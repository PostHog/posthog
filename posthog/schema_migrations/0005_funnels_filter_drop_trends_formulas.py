from posthog.schema_migrations.base import SchemaMigration

TRENDS_FORMULA_KEYS = ("formula", "formulas", "formulaNodes")


class Migration(SchemaMigration):
    """Drop trends-only formula keys from `funnelsFilter`.

    A trends formula edit could land in `funnelsFilter` when the insight switched to a funnel
    while the edit was still debounced. `FunnelsFilter` forbids unknown keys, so such a saved
    funnel fails validation on every query.
    """

    targets = {"FunnelsQuery": 2}

    def transform(self, query: dict) -> dict:
        funnels_filter = query.get("funnelsFilter")
        if not isinstance(funnels_filter, dict) or not any(key in funnels_filter for key in TRENDS_FORMULA_KEYS):
            return query

        query = dict(query)
        query["funnelsFilter"] = {k: v for k, v in funnels_filter.items() if k not in TRENDS_FORMULA_KEYS}
        return query
