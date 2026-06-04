from django.test.testcases import SimpleTestCase

from parameterized import parameterized

from posthog.schema import AssistantTrendsFilter, QuerySchemaRoot, TrendsFilter, TrendsQuery


class TestForwardCompatibleFilters(SimpleTestCase):
    # `bin/patch-schema-forward-compatible-filters.py` relaxes these models from
    # extra="forbid" to extra="ignore" so persisted/replayed query JSON survives
    # additive fields (rolling deploys) and leaked visualization-only keys. If a
    # schema regeneration ever loses the patch, these tests fail loudly.

    @parameterized.expand([("TrendsFilter", TrendsFilter), ("AssistantTrendsFilter", AssistantTrendsFilter)])
    def test_unknown_keys_are_ignored_not_rejected(self, _name: str, model: type) -> None:
        instance = model.model_validate({"showLegend": True, "yAxis": {"label": "Revenue"}, "totallyMadeUp": 1})

        assert instance.showLegend is True
        # extra="ignore" drops unknown keys rather than retaining them in the dump.
        dumped = instance.model_dump(exclude_none=True)
        assert "yAxis" not in dumped
        assert "totallyMadeUp" not in dumped

    def test_trends_query_with_unknown_trends_filter_key_validates(self) -> None:
        # Mirrors csv_exporter._query_supports_limit and the /query actor drilldown,
        # both of which re-validate a stored trendsFilter through QuerySchemaRoot.
        query = {
            "kind": "TrendsQuery",
            "series": [],
            "trendsFilter": {"showLegend": True, "yAxis": {"label": "Revenue"}},
        }

        QuerySchemaRoot.model_validate(query)
        TrendsQuery.model_validate(query)
