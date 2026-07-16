"""Tests for the v2 eval report schema."""

from django.test import SimpleTestCase

from posthog.temporal.ai_observability.eval_reports.output_types import SUPPORTED_EVAL_REPORT_OUTPUT_TYPES
from posthog.temporal.ai_observability.eval_reports.report_agent.schema import (
    MAX_REPORT_SECTIONS,
    MIN_REPORT_SECTIONS,
    Citation,
    EvalReportContent,
    EvalReportMetrics,
    ReportSection,
)

from products.ai_observability.backend.models.evaluation_configs import REPORTABLE_OUTPUT_TYPES


class TestOutputTypeRegistry(SimpleTestCase):
    def test_backend_reportability_matches_report_adapters(self):
        self.assertSetEqual(set(REPORTABLE_OUTPUT_TYPES), set(SUPPORTED_EVAL_REPORT_OUTPUT_TYPES))


class TestCitation(SimpleTestCase):
    def test_to_dict(self):
        c = Citation(generation_id="a-gen-id", trace_id="a-trace-id", reason="high_cost")
        self.assertEqual(
            c.to_dict(),
            {"generation_id": "a-gen-id", "trace_id": "a-trace-id", "reason": "high_cost"},
        )

    def test_from_dict(self):
        c = Citation.from_dict({"generation_id": "g", "trace_id": "t", "reason": "refusal"})
        self.assertEqual(c.generation_id, "g")
        self.assertEqual(c.trace_id, "t")
        self.assertEqual(c.reason, "refusal")

    def test_from_dict_missing_fields(self):
        c = Citation.from_dict({})
        self.assertEqual(c.generation_id, "")
        self.assertEqual(c.trace_id, "")
        self.assertEqual(c.reason, "")

    def test_roundtrip(self):
        original = Citation(generation_id="g1", trace_id="t1", reason="some reason")
        self.assertEqual(Citation.from_dict(original.to_dict()), original)


class TestReportSection(SimpleTestCase):
    def test_to_dict(self):
        s = ReportSection(title="Summary", content="Pass rate is 94%.")
        self.assertEqual(s.to_dict(), {"title": "Summary", "content": "Pass rate is 94%."})

    def test_from_dict(self):
        s = ReportSection.from_dict({"title": "T", "content": "C"})
        self.assertEqual(s.title, "T")
        self.assertEqual(s.content, "C")

    def test_from_dict_missing_fields(self):
        s = ReportSection.from_dict({})
        self.assertEqual(s.title, "")
        self.assertEqual(s.content, "")

    def test_roundtrip(self):
        original = ReportSection(title="Regression at 14:00", content="**pass rate dropped**")
        self.assertEqual(ReportSection.from_dict(original.to_dict()), original)


class TestEvalReportMetrics(SimpleTestCase):
    def test_to_dict(self):
        m = EvalReportMetrics(
            total_runs=100,
            result_counts={"pass": 80, "fail": 18, "na": 2},
            period_start="2026-04-08T14:00:00+00:00",
            period_end="2026-04-08T15:00:00+00:00",
            previous_total_runs=90,
            previous_result_counts={"pass": 60, "fail": 20, "na": 10},
        )
        self.assertEqual(
            m.to_dict(),
            {
                "output_type": "boolean",
                "total_runs": 100,
                "result_counts": {"pass": 80, "fail": 18, "na": 2},
                "result_rates": {"pass": 80.0, "fail": 18.0, "na": 2.0},
                "period_start": "2026-04-08T14:00:00+00:00",
                "period_end": "2026-04-08T15:00:00+00:00",
                "previous_total_runs": 90,
                "previous_result_counts": {"pass": 60, "fail": 20, "na": 10},
                "previous_result_rates": {"pass": 66.67, "fail": 22.22, "na": 11.11},
                "pass_rate": 81.63,
                "previous_pass_rate": 75.0,
            },
        )

    def test_from_dict_defaults(self):
        m = EvalReportMetrics.from_dict({})
        self.assertEqual(m.total_runs, 0)
        self.assertEqual(m.output_type, "boolean")
        self.assertEqual(m.result_counts, {"pass": 0, "fail": 0, "na": 0})
        self.assertEqual(m.result_rates, {"pass": 0.0, "fail": 0.0, "na": 0.0})
        self.assertEqual(m.pass_rate, 0.0)
        self.assertEqual(m.period_start, "")
        self.assertIsNone(m.previous_pass_rate)
        self.assertIsNone(m.previous_total_runs)

    def test_normalizes_legacy_boolean_json(self):
        metrics = EvalReportMetrics.from_dict(
            {
                "total_runs": 11,
                "pass_count": 8,
                "fail_count": 2,
                "na_count": 1,
                "pass_rate": 80.0,
                "previous_total_runs": 5,
                "previous_pass_rate": 60.0,
            }
        )

        self.assertEqual(metrics.output_type, "boolean")
        self.assertEqual(metrics.result_counts, {"pass": 8, "fail": 2, "na": 1})
        self.assertEqual(metrics.result_rates, {"pass": 72.73, "fail": 18.18, "na": 9.09})
        self.assertIsNone(metrics.previous_result_counts)
        self.assertIsNone(metrics.previous_result_rates)
        self.assertEqual(metrics.previous_pass_rate, 60.0)
        self.assertNotIn("pass_count", metrics.to_dict())
        self.assertNotIn("fail_count", metrics.to_dict())
        self.assertNotIn("na_count", metrics.to_dict())

    def test_preserves_legacy_pass_rate_when_counts_are_partial(self):
        metrics = EvalReportMetrics.from_dict({"total_runs": 10, "pass_count": 9, "pass_rate": 90.0})

        self.assertEqual(metrics.pass_rate, 90.0)
        self.assertEqual(metrics.result_rates["pass"], 100.0)

    def test_sentiment_metrics_roundtrip(self):
        original = EvalReportMetrics(
            output_type="sentiment",
            total_runs=4,
            result_counts={"positive": 2, "neutral": 1, "negative": 1},
            period_start="2026-04-08T00:00:00+00:00",
            period_end="2026-04-08T01:00:00+00:00",
            previous_total_runs=2,
            previous_result_counts={"positive": 1, "neutral": 1, "negative": 0},
        )

        roundtripped = EvalReportMetrics.from_dict(original.to_dict())

        self.assertEqual(roundtripped, original)
        self.assertEqual(roundtripped.result_rates, {"positive": 50.0, "neutral": 25.0, "negative": 25.0})
        self.assertEqual(
            roundtripped.previous_result_rates,
            {"positive": 50.0, "neutral": 50.0, "negative": 0.0},
        )
        self.assertNotIn("pass_count", original.to_dict())

    def test_roundtrip_with_nulls(self):
        original = EvalReportMetrics(
            total_runs=5,
            result_counts={"pass": 5, "fail": 0, "na": 0},
            period_start="2026-04-08T00:00:00+00:00",
            period_end="2026-04-08T01:00:00+00:00",
            previous_total_runs=None,
            previous_pass_rate=None,
        )
        self.assertEqual(EvalReportMetrics.from_dict(original.to_dict()), original)


class TestEvalReportContent(SimpleTestCase):
    def test_default_is_empty(self):
        c = EvalReportContent()
        self.assertEqual(c.title, "")
        self.assertEqual(c.sections, [])
        self.assertEqual(c.citations, [])
        self.assertIsInstance(c.metrics, EvalReportMetrics)

    def test_to_dict_populated(self):
        c = EvalReportContent(
            title="Pass rate steady at 94%",
            sections=[
                ReportSection(title="Summary", content="All good."),
                ReportSection(title="Caveats", content="One dip at 14:00."),
            ],
            citations=[Citation(generation_id="g1", trace_id="t1", reason="example")],
            metrics=EvalReportMetrics(total_runs=53, result_counts={"pass": 50, "fail": 3, "na": 0}),
        )
        d = c.to_dict()
        self.assertEqual(d["title"], "Pass rate steady at 94%")
        self.assertEqual(len(d["sections"]), 2)
        self.assertEqual(d["sections"][0]["title"], "Summary")
        self.assertEqual(len(d["citations"]), 1)
        self.assertEqual(d["citations"][0]["generation_id"], "g1")
        self.assertEqual(d["metrics"]["total_runs"], 53)

    def test_from_dict_empty(self):
        c = EvalReportContent.from_dict({})
        self.assertEqual(c.title, "")
        self.assertEqual(c.sections, [])
        self.assertEqual(c.citations, [])
        self.assertIsInstance(c.metrics, EvalReportMetrics)

    def test_from_dict_populated(self):
        c = EvalReportContent.from_dict(
            {
                "title": "T",
                "sections": [
                    {"title": "S1", "content": "C1"},
                    {"title": "S2", "content": "C2"},
                ],
                "citations": [{"generation_id": "g", "trace_id": "t", "reason": "r"}],
                "metrics": {"total_runs": 10, "pass_rate": 90.0},
            }
        )
        self.assertEqual(c.title, "T")
        self.assertEqual(len(c.sections), 2)
        self.assertEqual(c.sections[1].content, "C2")
        self.assertEqual(c.citations[0].reason, "r")
        self.assertEqual(c.metrics.total_runs, 10)

    def test_roundtrip(self):
        original = EvalReportContent(
            title="T",
            sections=[ReportSection(title="S", content="C")],
            citations=[Citation(generation_id="g", trace_id="t", reason="r")],
            metrics=EvalReportMetrics(total_runs=1, result_counts={"pass": 1, "fail": 0, "na": 0}),
        )
        roundtripped = EvalReportContent.from_dict(original.to_dict())
        self.assertEqual(roundtripped.title, original.title)
        self.assertEqual(len(roundtripped.sections), 1)
        self.assertEqual(roundtripped.sections[0], original.sections[0])
        self.assertEqual(roundtripped.citations[0], original.citations[0])
        self.assertEqual(roundtripped.metrics, original.metrics)


class TestSectionBounds(SimpleTestCase):
    def test_min_and_max_constants(self):
        # Contract with the agent prompt — if these change, prompt must change too.
        self.assertEqual(MIN_REPORT_SECTIONS, 1)
        self.assertEqual(MAX_REPORT_SECTIONS, 6)
