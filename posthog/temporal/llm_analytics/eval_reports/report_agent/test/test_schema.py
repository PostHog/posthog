from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import (
    REPORT_SECTIONS,
    EvalReportContent,
    EvalReportMetadata,
    ReportSection,
)


class TestReportSection(SimpleTestCase):
    def test_to_dict_basic(self):
        section = ReportSection(content="hello", referenced_generation_ids=["abc"])
        result = section.to_dict()
        self.assertEqual(result, {"content": "hello", "referenced_generation_ids": ["abc"]})

    def test_from_dict_basic(self):
        section = ReportSection.from_dict({"content": "test", "referenced_generation_ids": ["id1", "id2"]})
        self.assertEqual(section.content, "test")
        self.assertEqual(section.referenced_generation_ids, ["id1", "id2"])

    def test_from_dict_missing_fields(self):
        section = ReportSection.from_dict({})
        self.assertEqual(section.content, "")
        self.assertEqual(section.referenced_generation_ids, [])

    def test_roundtrip(self):
        original = ReportSection(content="analysis", referenced_generation_ids=["a", "b", "c"])
        rebuilt = ReportSection.from_dict(original.to_dict())
        self.assertEqual(rebuilt.content, original.content)
        self.assertEqual(rebuilt.referenced_generation_ids, original.referenced_generation_ids)


class TestEvalReportContent(SimpleTestCase):
    def test_to_dict_empty(self):
        content = EvalReportContent()
        self.assertEqual(content.to_dict(), {})

    def test_to_dict_with_sections(self):
        content = EvalReportContent(
            executive_summary=ReportSection(content="summary"),
            statistics=ReportSection(content="stats"),
        )
        result = content.to_dict()
        self.assertEqual(set(result.keys()), {"executive_summary", "statistics"})
        self.assertEqual(result["executive_summary"]["content"], "summary")

    def test_from_dict_empty(self):
        content = EvalReportContent.from_dict({})
        for section_name in REPORT_SECTIONS:
            self.assertIsNone(getattr(content, section_name))

    def test_from_dict_ignores_none_values(self):
        content = EvalReportContent.from_dict({"executive_summary": None})
        self.assertIsNone(content.executive_summary)

    def test_roundtrip_all_sections(self):
        original = EvalReportContent()
        for name in REPORT_SECTIONS:
            setattr(original, name, ReportSection(content=f"content for {name}", referenced_generation_ids=[name]))
        rebuilt = EvalReportContent.from_dict(original.to_dict())
        for name in REPORT_SECTIONS:
            orig = getattr(original, name)
            reblt = getattr(rebuilt, name)
            self.assertIsNotNone(reblt)
            self.assertEqual(reblt.content, orig.content)
            self.assertEqual(reblt.referenced_generation_ids, orig.referenced_generation_ids)

    def test_from_dict_partial_sections(self):
        content = EvalReportContent.from_dict(
            {
                "executive_summary": {"content": "summary", "referenced_generation_ids": []},
                "recommendations": {"content": "recs", "referenced_generation_ids": ["id1"]},
            }
        )
        self.assertIsNotNone(content.executive_summary)
        self.assertIsNotNone(content.recommendations)
        self.assertIsNone(content.statistics)
        self.assertIsNone(content.trend_analysis)


class TestEvalReportMetadata(SimpleTestCase):
    def test_to_dict(self):
        meta = EvalReportMetadata(
            total_runs=100, pass_count=80, fail_count=15, na_count=5, pass_rate=84.21, previous_pass_rate=75.0
        )
        result = meta.to_dict()
        self.assertEqual(result["total_runs"], 100)
        self.assertEqual(result["pass_rate"], 84.21)
        self.assertEqual(result["previous_pass_rate"], 75.0)

    def test_from_dict(self):
        meta = EvalReportMetadata.from_dict(
            {
                "total_runs": 50,
                "pass_count": 40,
                "fail_count": 8,
                "na_count": 2,
                "pass_rate": 83.33,
                "previous_pass_rate": None,
            }
        )
        self.assertEqual(meta.total_runs, 50)
        self.assertIsNone(meta.previous_pass_rate)

    def test_from_dict_defaults(self):
        meta = EvalReportMetadata.from_dict({})
        self.assertEqual(meta.total_runs, 0)
        self.assertEqual(meta.pass_rate, 0.0)
        self.assertIsNone(meta.previous_pass_rate)

    def test_roundtrip(self):
        original = EvalReportMetadata(
            total_runs=200, pass_count=150, fail_count=40, na_count=10, pass_rate=78.95, previous_pass_rate=82.0
        )
        rebuilt = EvalReportMetadata.from_dict(original.to_dict())
        self.assertEqual(rebuilt.total_runs, original.total_runs)
        self.assertEqual(rebuilt.pass_rate, original.pass_rate)
        self.assertEqual(rebuilt.previous_pass_rate, original.previous_pass_rate)

    @parameterized.expand(
        [
            ("with_previous", 75.0),
            ("without_previous", None),
        ]
    )
    def test_previous_pass_rate_variants(self, _name, previous_pass_rate):
        meta = EvalReportMetadata(pass_rate=80.0, previous_pass_rate=previous_pass_rate)
        rebuilt = EvalReportMetadata.from_dict(meta.to_dict())
        self.assertEqual(rebuilt.previous_pass_rate, previous_pass_rate)
