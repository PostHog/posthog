"""Tests for the v2 eval report schema."""

from django.test import SimpleTestCase

from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import (
    MAX_REPORT_SECTIONS,
    MIN_REPORT_SECTIONS,
    Citation,
    EvalReportContent,
    EvalReportMetrics,
    ReportSection,
)


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
            pass_count=80,
            fail_count=18,
            na_count=2,
            pass_rate=81.63,
            period_start="2026-04-08T14:00:00+00:00",
            period_end="2026-04-08T15:00:00+00:00",
            previous_total_runs=90,
            previous_pass_rate=75.0,
        )
        self.assertEqual(
            m.to_dict(),
            {
                "total_runs": 100,
                "pass_count": 80,
                "fail_count": 18,
                "na_count": 2,
                "pass_rate": 81.63,
                "period_start": "2026-04-08T14:00:00+00:00",
                "period_end": "2026-04-08T15:00:00+00:00",
                "previous_total_runs": 90,
                "previous_pass_rate": 75.0,
            },
        )

    def test_from_dict_defaults(self):
        m = EvalReportMetrics.from_dict({})
        self.assertEqual(m.total_runs, 0)
        self.assertEqual(m.pass_count, 0)
        self.assertEqual(m.pass_rate, 0.0)
        self.assertEqual(m.period_start, "")
        self.assertIsNone(m.previous_pass_rate)
        self.assertIsNone(m.previous_total_runs)

    def test_roundtrip_with_nulls(self):
        original = EvalReportMetrics(
            total_runs=5,
            pass_count=5,
            fail_count=0,
            na_count=0,
            pass_rate=100.0,
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
            metrics=EvalReportMetrics(total_runs=53, pass_count=50, fail_count=3, pass_rate=94.34),
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
            metrics=EvalReportMetrics(total_runs=1, pass_rate=100.0),
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
