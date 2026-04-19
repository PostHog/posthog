from parameterized import parameterized_class

from posthog.temporal.subscriptions.results_summarizer import MAX_SUMMARY_LENGTH, build_results_summary


class TestBuildResultsSummaryEmpty:
    def test_none_results(self):
        assert build_results_summary("TrendsQuery", None) == "No results"

    def test_empty_list(self):
        assert build_results_summary("TrendsQuery", []) == "No results"


@parameterized_class(
    ("name", "query_kind", "results", "expected_fragments"),
    [
        (
            "trends_with_data",
            "TrendsQuery",
            [
                {"label": "Pageviews", "data": [100, 120, 110, 130, 150]},
                {"label": "Signups", "data": [10, 12, 8, 15, 20]},
            ],
            ["Pageviews", "latest=150", "avg=", "trend=up", "Signups", "latest=20"],
        ),
        (
            "trends_with_count_only",
            "TrendsQuery",
            [{"label": "Total events", "count": 42, "aggregated_value": None}],
            ["Total events", "count=42"],
        ),
        (
            "trends_bold_number",
            "TrendsQuery",
            [{"label": "Bills paid", "data": [], "count": 0, "aggregated_value": 20}],
            ["Bills paid", "total=20"],
        ),
        (
            "trends_bold_number_float",
            "TrendsQuery",
            [{"label": "Revenue", "data": [], "count": 0, "aggregated_value": 1234.56}],
            ["Revenue", "total=1,234.56"],
        ),
        (
            "trends_stable",
            "TrendsQuery",
            [{"label": "Flat metric", "data": [100, 100, 100, 100]}],
            ["Flat metric", "trend=stable"],
        ),
        (
            "trends_down",
            "TrendsQuery",
            [{"label": "Declining", "data": [200, 180, 100, 80]}],
            ["Declining", "trend=down"],
        ),
        (
            "funnels_basic",
            "FunnelsQuery",
            [
                {"name": "Visit page", "count": 1000, "conversion_rate": 100},
                {"name": "Click button", "count": 500, "conversion_rate": 50},
                {"name": "Submit form", "count": 100, "conversion_rate": 10},
            ],
            ["Step 1 (Visit page)", "count=1,000", "conversion=100%", "Step 3 (Submit form)", "conversion=10%"],
        ),
        (
            "funnels_nested",
            "FunnelsQuery",
            [
                [
                    {"name": "Step A", "count": 500, "conversion_rate": 100},
                    {"name": "Step B", "count": 250, "conversion_rate": 50},
                ]
            ],
            ["Step 1 (Step A)", "Step 2 (Step B)", "conversion=50%"],
        ),
        (
            "retention_basic",
            "RetentionQuery",
            [
                {"label": "Week 0", "values": [{"count": 1000}, {"count": 500}, {"count": 250}]},
                {"label": "Week 1", "values": [{"count": 800}, {"count": 300}]},
            ],
            ["Week 0", "initial=1,000", "final=250", "retention=25%", "Week 1"],
        ),
        (
            "lifecycle_uses_trends",
            "LifecycleQuery",
            [{"label": "New", "data": [10, 20, 30]}],
            ["New", "latest=30", "trend=up"],
        ),
        (
            "unknown_query_uses_generic",
            "PathsQuery",
            [{"source": "/home", "target": "/about", "value": 42}],
            ["source=/home", "target=/about", "value=42"],
        ),
    ],
)
class TestBuildResultsSummary:
    name: str
    query_kind: str
    results: list
    expected_fragments: list[str]

    def test_summary_contains_expected_fragments(self):
        summary = build_results_summary(self.query_kind, self.results)
        for fragment in self.expected_fragments:
            assert fragment in summary, f"Expected '{fragment}' in summary:\n{summary}"


class TestBuildResultsSummaryTruncation:
    def test_long_results_are_truncated(self):
        results = [{"label": f"Series {i}", "data": list(range(100))} for i in range(50)]
        summary = build_results_summary("TrendsQuery", results)
        assert len(summary) <= MAX_SUMMARY_LENGTH + len("\n... (truncated)")
        assert "truncated" in summary


class TestBuildResultsSummaryEdgeCases:
    def test_inf_values_do_not_crash(self):
        results = [{"label": "Metric", "data": [1.0, float("inf"), 3.0]}]
        summary = build_results_summary("TrendsQuery", results)
        assert "Metric" in summary

    def test_nan_values_do_not_crash(self):
        results = [{"label": "Metric", "data": [1.0, float("nan"), 3.0]}]
        summary = build_results_summary("TrendsQuery", results)
        assert "Metric" in summary

    def test_aggregated_value_with_inf(self):
        results = [{"label": "Metric", "data": [], "count": 0, "aggregated_value": float("inf")}]
        summary = build_results_summary("TrendsQuery", results)
        assert "N/A" in summary
