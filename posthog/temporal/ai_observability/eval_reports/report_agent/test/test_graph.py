"""Tests for the v2 graph helpers: _fallback_content and _validate_agent_output."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.temporal.ai_observability.eval_reports.report_agent import graph
from posthog.temporal.ai_observability.eval_reports.report_agent.graph import (
    _append_references_section,
    _fallback_content,
    _validate_agent_output,
)
from posthog.temporal.ai_observability.eval_reports.report_agent.prompts import build_eval_report_system_prompt
from posthog.temporal.ai_observability.eval_reports.report_agent.schema import (
    MAX_REPORT_SECTIONS,
    Citation,
    EvalReportContent,
    EvalReportMetrics,
    ReportSection,
)


class TestSystemPromptFormat(SimpleTestCase):
    def _build_prompt(
        self, output_type: str = "boolean", guidance: str = "", evaluation_target: str = "generation"
    ) -> str:
        return build_eval_report_system_prompt(
            evaluation_name="Test Eval",
            evaluation_description="foo",
            evaluation_type="llm_judge",
            evaluation_prompt="criteria",
            evaluation_target=evaluation_target,
            output_type=output_type,
            period_start="2026-04-08T14:00:00+00:00",
            period_end="2026-04-08T15:00:00+00:00",
            report_prompt_guidance=guidance,
        )

    def test_format_with_all_expected_args(self):
        formatted = self._build_prompt()
        self.assertIn("Test Eval", formatted)
        self.assertIn("llm_judge", formatted)
        self.assertIn(str(MAX_REPORT_SECTIONS), formatted)
        self.assertNotIn("{", formatted.split("```")[0])  # No unfilled placeholders

    def test_format_with_guidance_section(self):
        formatted = self._build_prompt(guidance="Focus on cost regressions")
        self.assertIn("Focus on cost regressions", formatted)

    def test_sentiment_prompt_explains_semantics_without_pass_rate_framing(self):
        formatted = self._build_prompt(output_type="sentiment")

        self.assertIn("classify the user messages", formatted)
        self.assertIn("not response quality", formatted)
        self.assertIn('outcome="all"|"positive"|"neutral"|"negative"', formatted)
        self.assertNotIn("pass rate", formatted.lower())

    def test_trace_prompt_uses_only_trace_detail_workflow(self):
        formatted = self._build_prompt(evaluation_target="trace")

        self.assertIn("Evaluation target: trace", formatted)
        self.assertIn("sample_trace_details", formatted)
        self.assertIn("get_trace_detail", formatted)
        self.assertIn('generation_id=""', formatted)
        self.assertNotIn("sample_generation_details", formatted)
        self.assertIn("trace satisfied the configured criteria", formatted)


class TestComputeMetrics(SimpleTestCase):
    @patch.object(graph, "_fetch_period_summary")
    def test_computes_sentiment_rates_from_all_known_labels(self, mock_fetch):
        mock_fetch.side_effect = [
            ({"positive": 2, "neutral": 1, "negative": 1}, 4),
            ({"positive": 1, "neutral": 1, "negative": 0}, 2),
        ]

        metrics = graph._compute_metrics(
            team_id=1,
            evaluation_id="eval-id",
            period_start="2026-04-08T14:00:00+00:00",
            period_end="2026-04-08T15:00:00+00:00",
            previous_period_start="2026-04-08T13:00:00+00:00",
            output_type="sentiment",
        )

        self.assertEqual(metrics.result_rates, {"positive": 50.0, "neutral": 25.0, "negative": 25.0})
        self.assertEqual(metrics.previous_result_rates, {"positive": 50.0, "neutral": 50.0, "negative": 0.0})


class TestFallbackContent(SimpleTestCase):
    def test_zero_runs_produces_no_runs_message(self):
        metrics = EvalReportMetrics(
            total_runs=0,
            result_counts={"pass": 0, "fail": 0, "na": 0},
            period_start="2026-04-08T14:00:00+00:00",
            period_end="2026-04-08T15:00:00+00:00",
        )
        content = _fallback_content("Relevance", metrics, "agent timed out")
        self.assertIn("Relevance", content.title)
        self.assertEqual(len(content.sections), 1)
        self.assertIn("No evaluation runs", content.sections[0].content)
        self.assertIn("agent timed out", content.sections[0].content)
        self.assertEqual(content.metrics, metrics)

    def test_trace_zero_runs_uses_trace_specific_ingestion_hint(self):
        metrics = EvalReportMetrics(total_runs=0)

        content = _fallback_content("Trace quality", metrics, "agent timed out", evaluation_target="trace")

        self.assertIn("trace evaluation results", content.sections[0].content)
        self.assertNotIn("$ai_generation", content.sections[0].content)
        self.assertEqual(content.evaluation_target, "trace")

    def test_populated_metrics_stable_trend(self):
        metrics = EvalReportMetrics(
            total_runs=100,
            result_counts={"pass": 80, "fail": 20, "na": 0},
            previous_pass_rate=80.0,
        )
        content = _fallback_content("Helpfulness", metrics, "validation failed")
        self.assertEqual(len(content.sections), 1)
        body = content.sections[0].content
        self.assertIn("80.0%", body)
        self.assertIn("stable", body)

    @parameterized.expand(
        [
            ("trend_up", 90.0, 70.0, "up from"),
            ("trend_down", 50.0, 80.0, "down from"),
        ]
    )
    def test_populated_metrics_trend(self, _name, pass_rate, previous_pass_rate, expected_phrase):
        metrics = EvalReportMetrics(
            total_runs=10,
            result_counts={
                "pass": int(pass_rate / 10),
                "fail": 10 - int(pass_rate / 10),
                "na": 0,
            },
            previous_pass_rate=previous_pass_rate,
        )
        content = _fallback_content("X", metrics, "why")
        self.assertIn(expected_phrase, content.sections[0].content)

    def test_includes_fallback_note(self):
        metrics = EvalReportMetrics(total_runs=1, result_counts={"pass": 1, "fail": 0, "na": 0})
        content = _fallback_content("X", metrics, "custom reason here")
        self.assertIn("custom reason here", content.sections[0].content)
        self.assertIn("fallback", content.sections[0].content.lower())

    def test_citations_empty(self):
        metrics = EvalReportMetrics(total_runs=0)
        content = _fallback_content("X", metrics, "reason")
        self.assertEqual(content.citations, [])

    def test_sentiment_fallback_reports_distribution_without_pass_rate_framing(self):
        metrics = EvalReportMetrics(
            output_type="sentiment",
            total_runs=4,
            result_counts={"positive": 2, "neutral": 1, "negative": 1},
            previous_result_counts={"positive": 1, "neutral": 1, "negative": 0},
        )

        content = _fallback_content("Tone", metrics, "agent timed out")
        body = content.sections[0].content

        self.assertIn("Positive 50.0%", body)
        self.assertIn("Neutral 25.0%", body)
        self.assertIn("Negative 25.0%", body)
        self.assertNotIn("pass rate", body.lower())


class TestValidateAgentOutput(SimpleTestCase):
    def _valid_content(self) -> EvalReportContent:
        return EvalReportContent(
            title="A valid punchline",
            sections=[ReportSection(title="Summary", content="A finding.")],
            citations=[],
            metrics=EvalReportMetrics(),
        )

    def test_valid_content_returns_none(self):
        content = self._valid_content()
        self.assertIsNone(_validate_agent_output(content))

    def test_missing_title_fails(self):
        content = self._valid_content()
        content.title = ""
        self.assertIsNotNone(_validate_agent_output(content))

    def test_whitespace_title_fails(self):
        content = self._valid_content()
        content.title = "   "
        self.assertIsNotNone(_validate_agent_output(content))

    def test_zero_sections_fails(self):
        content = self._valid_content()
        content.sections = []
        reason = _validate_agent_output(content)
        self.assertIsNotNone(reason)
        self.assertIn("0", reason or "")

    def test_too_many_sections_fails(self):
        content = self._valid_content()
        content.sections = [ReportSection(title=f"S{i}", content=f"c{i}") for i in range(MAX_REPORT_SECTIONS + 1)]
        reason = _validate_agent_output(content)
        self.assertIsNotNone(reason)
        self.assertIn("maximum", reason or "")

    def test_exactly_max_sections_passes(self):
        content = self._valid_content()
        content.sections = [ReportSection(title=f"S{i}", content=f"c{i}") for i in range(MAX_REPORT_SECTIONS)]
        self.assertIsNone(_validate_agent_output(content))

    def test_empty_section_title_fails(self):
        content = self._valid_content()
        content.sections.append(ReportSection(title="", content="body"))
        self.assertIsNotNone(_validate_agent_output(content))

    def test_empty_section_content_fails(self):
        content = self._valid_content()
        content.sections.append(ReportSection(title="Title", content=""))
        self.assertIsNotNone(_validate_agent_output(content))

    def test_citations_do_not_affect_validation(self):
        content = self._valid_content()
        content.citations = [Citation(generation_id="g", trace_id="t", reason="r")]
        self.assertIsNone(_validate_agent_output(content))


class TestAppendReferencesSection(SimpleTestCase):
    def test_no_citations_leaves_sections_untouched(self):
        content = EvalReportContent(
            title="t",
            sections=[ReportSection(title="S1", content="c1")],
            citations=[],
        )
        _append_references_section(content)
        self.assertEqual(len(content.sections), 1)

    def test_appends_references_as_final_section(self):
        content = EvalReportContent(
            title="t",
            sections=[ReportSection(title="S1", content="c1")],
            citations=[Citation(generation_id="g1", trace_id="t1", reason="r1")],
        )
        _append_references_section(content)
        self.assertEqual(len(content.sections), 2)
        self.assertEqual(content.sections[-1].title, "References")
        self.assertIn("g1", content.sections[-1].content)

    def test_trace_reference_uses_trace_id_when_generation_id_is_empty(self):
        content = EvalReportContent(
            title="t",
            sections=[ReportSection(title="S1", content="c1")],
            citations=[Citation(generation_id="", trace_id="customer-trace/42", reason="r1")],
        )

        _append_references_section(content)

        self.assertIn("customer-trace/42", content.sections[-1].content)

    def test_references_does_not_displace_content_at_max_sections(self):
        # Regression: previously the auto-appended References section replaced
        # the agent's final section when agent produced MAX_REPORT_SECTIONS.
        content = EvalReportContent(
            title="t",
            sections=[ReportSection(title=f"S{i}", content=f"c{i}") for i in range(MAX_REPORT_SECTIONS)],
            citations=[Citation(generation_id="g1", trace_id="t1", reason="r1")],
        )
        _append_references_section(content)
        self.assertEqual(len(content.sections), MAX_REPORT_SECTIONS + 1)
        # Agent's last section is preserved
        self.assertEqual(content.sections[MAX_REPORT_SECTIONS - 1].title, f"S{MAX_REPORT_SECTIONS - 1}")
        self.assertEqual(content.sections[-1].title, "References")


class TestRunEvalReportAgentRouting(SimpleTestCase):
    """The report agent builds its LLM client via the shared ai-gateway helper.

    Pins the gateway routing at the call site: reverting to a direct ChatOpenAI(...)
    fails this test even though the agent run itself is mocked out.
    """

    @patch.object(graph, "posthoganalytics")
    @patch.object(graph, "create_react_agent")
    @patch.object(graph, "build_langchain_chat_client")
    @patch.object(graph, "_compute_metrics")
    def test_routes_llm_through_gateway_helper(self, mock_metrics, mock_build_llm, mock_create_agent, mock_pha):
        from posthog.temporal.ai_observability.eval_reports.constants import (
            EVAL_REPORT_AGENT_MODEL,
            EVAL_REPORT_AGENT_TIMEOUT,
        )

        mock_pha.default_client = None  # skip the analytics callback
        mock_metrics.return_value = EvalReportMetrics()
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "report": EvalReportContent(
                title="A report",
                sections=[ReportSection(title="Summary", content="A finding.")],
                metrics=EvalReportMetrics(),
            )
        }
        mock_create_agent.return_value = mock_agent

        graph.run_eval_report_agent(
            team_id=1,
            evaluation_id="eval-1",
            evaluation_name="Relevance",
            evaluation_description="",
            evaluation_prompt="",
            evaluation_type="llm_judge",
            period_start="2026-04-08T14:00:00+00:00",
            period_end="2026-04-08T15:00:00+00:00",
            previous_period_start="2026-04-08T13:00:00+00:00",
        )

        mock_build_llm.assert_called_once_with(
            EVAL_REPORT_AGENT_MODEL, EVAL_REPORT_AGENT_TIMEOUT, ai_product="aio_eval_reports"
        )
        # the agent is built with the gateway-helper client, not a directly-constructed one
        self.assertIs(mock_create_agent.call_args.kwargs["model"], mock_build_llm.return_value)


class TestRunEvalReportAgentCallbackGating(SimpleTestCase):
    """The SDK CallbackHandler fires only when NOT routing through the gateway.

    In gateway mode the Go gateway captures $ai_generation itself, so attaching the
    SDK callback too would double-count every eval-report LLM call. The gate is the
    same resolve_ai_gateway_config() the model routing reads. Reverting the guard
    (dropping `and resolve_ai_gateway_config() is None`) fails the gateway-on case.
    """

    def _run_and_get_callbacks(self, mock_create_agent):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "report": EvalReportContent(
                title="A report",
                sections=[ReportSection(title="Summary", content="A finding.")],
                metrics=EvalReportMetrics(),
            )
        }
        mock_create_agent.return_value = mock_agent
        graph.run_eval_report_agent(
            team_id=1,
            evaluation_id="eval-1",
            evaluation_name="Relevance",
            evaluation_description="",
            evaluation_prompt="",
            evaluation_type="llm_judge",
            period_start="2026-04-08T14:00:00+00:00",
            period_end="2026-04-08T15:00:00+00:00",
            previous_period_start="2026-04-08T13:00:00+00:00",
        )
        return mock_agent.invoke.call_args.args[1]["callbacks"]

    @patch.object(graph, "resolve_ai_gateway_config")
    @patch.object(graph, "CallbackHandler")
    @patch.object(graph, "posthoganalytics")
    @patch.object(graph, "create_react_agent")
    @patch.object(graph, "build_langchain_chat_client")
    @patch.object(graph, "_compute_metrics")
    def test_gateway_mode_attaches_no_callback(
        self, mock_metrics, mock_build_llm, mock_create_agent, mock_pha, mock_cb, mock_resolve
    ):
        mock_metrics.return_value = EvalReportMetrics()
        mock_pha.default_client = MagicMock()  # analytics client available...
        mock_resolve.return_value = ("https://gateway.example/v1", "key")  # ...but gateway is live

        callbacks = self._run_and_get_callbacks(mock_create_agent)

        self.assertEqual(callbacks, [], "gateway mode must attach no SDK callback (the gateway captures the event)")
        mock_cb.assert_not_called()

    @patch.object(graph, "resolve_ai_gateway_config")
    @patch.object(graph, "CallbackHandler")
    @patch.object(graph, "posthoganalytics")
    @patch.object(graph, "create_react_agent")
    @patch.object(graph, "build_langchain_chat_client")
    @patch.object(graph, "_compute_metrics")
    def test_direct_mode_attaches_tagged_callback(
        self, mock_metrics, mock_build_llm, mock_create_agent, mock_pha, mock_cb, mock_resolve
    ):
        mock_metrics.return_value = EvalReportMetrics()
        mock_pha.default_client = MagicMock()
        mock_resolve.return_value = None  # no gateway -> direct OpenAI, SDK must capture the event

        callbacks = self._run_and_get_callbacks(mock_create_agent)

        self.assertEqual(len(callbacks), 1, "direct mode must attach the SDK callback so the run is captured")
        self.assertEqual(mock_cb.call_args.kwargs["properties"]["ai_product"], "llma_eval_reports")
