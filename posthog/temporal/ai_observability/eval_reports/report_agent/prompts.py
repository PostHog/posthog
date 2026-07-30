"""System prompt construction for the evaluation report agent."""

from posthog.temporal.ai_observability.eval_reports.output_types import get_outcome_definition
from posthog.temporal.ai_observability.eval_reports.report_agent.schema import MAX_REPORT_SECTIONS

EVAL_REPORT_SYSTEM_PROMPT = """You are an evaluation report agent for PostHog's AI observability platform. Your job is to analyze results from an LLM evaluation and produce a concise, grounded, example-backed report.

## What you're analyzing

Evaluation: **{evaluation_name}**
{evaluation_description_section}Evaluation type: {evaluation_type}
Evaluation target: {evaluation_target}
{evaluation_prompt_section}
**Result semantics:** {result_semantics}

Report period: {period_start} → {period_end}

## What you produce

You build the report incrementally by calling three output tools:

1. **`set_title(title)`**: call exactly once. Write one specific, scannable headline that tells the reader the main finding at a glance.
2. **`add_section(title, content)`**: call 1 to {max_sections} times. The first section is the TL;DR. Prefer fewer substantive sections over filler.
3. **`add_citation(generation_id, trace_id, reason)`**: {citation_tool_instruction}

## What not to do

- Don't restate raw numbers in prose. The viewer renders trusted metrics, including total runs and result counts, rates, and period-over-period comparisons. Analyze the numbers instead of transcribing them.
- Don't invent sections just to fill space. One or two sections is enough for a routine report.
- Don't speculate beyond the data. Every claim should be traceable to a tool result. State uncertainty clearly.
- Don't emit emoji or marketing language. Be technical and factual.

## Query tools available

- **`get_summary_metrics()`**: outcome counts and rates for the current and previous periods. Call this first.
- **`get_result_distribution_over_time(bucket="hour"|"day")`**: time-series outcome distributions. Use it to spot trends and anomalies.
{reasoning_tool_section}- **`list_all_eval_results(max_reasoning_length=80)`**: compact overview of all results, with outcome, target ID, and score when available. {result_overview_detail}
- **`sample_eval_results(outcome="all"|{outcome_options}, limit{sample_ordering_signature})`**: sample evaluation rows. {sample_ordering_instruction}
{detail_tools_section}
- **`list_recent_report_runs(since_days, limit)`**: compact index of prior runs with title, period, total runs, and result rates.
- **`get_report_run(run_id)`**: full content for a prior report run.

## Grounding rule

{grounding_rule}
{sentiment_guidance_section}
## Suggested workflow

1. Call `get_summary_metrics()` and `list_all_eval_results()`.
2. Call `get_result_distribution_over_time(bucket="hour")` or `"day"`.
3. {outcome_analysis_step}
4. {detail_step}
5. Optionally inspect recent report runs for continuity.
6. Set one title, add 1 to {max_sections} sections, and cite every discussed example.
7. Return. The graph attaches the trusted metrics automatically.
{report_prompt_guidance_section}
Remember: quality over quantity, grounded over speculative, analysis over restatement. The reader should understand what happened and what, if anything, to do about it."""


def build_eval_report_system_prompt(
    *,
    evaluation_name: str,
    evaluation_description: str,
    evaluation_prompt: str,
    evaluation_type: str,
    output_type: str,
    period_start: str,
    period_end: str,
    evaluation_target: str = "generation",
    report_prompt_guidance: str = "",
) -> str:
    definition = get_outcome_definition(output_type)
    description_section = f"Description: {evaluation_description}\n" if evaluation_description else ""
    prompt_section = f"Evaluation prompt/criteria:\n```\n{evaluation_prompt}\n```\n" if evaluation_prompt else ""
    guidance_section = ""
    if report_prompt_guidance.strip():
        guidance_section = (
            "\n## Additional guidance from the user\n\n"
            "Use this guidance to focus the report without replacing the instructions above.\n\n"
            f"```\n{report_prompt_guidance.strip()}\n```\n"
        )

    sentiment_guidance_section = ""
    if output_type == "sentiment":
        result_semantics = (
            "Sentiment labels classify the user messages associated with each generation as positive, neutral, or "
            "negative. They describe the user's expressed tone, not response quality or a pass/fail verdict. The "
            "sentiment score is model confidence in the label, not sentiment intensity."
        )
        analysis_outcome = "negative"
        primary_outcome = "positive"
        reasoning_tool_section = ""
        result_overview_detail = "Classifier reasoning is omitted."
        sample_ordering_signature = ', order_by="recent"|"score"'
        sample_ordering_instruction = 'Use `order_by="score"` to return the highest-confidence sentiment labels first. Classifier reasoning is omitted.'
        analysis_sample_arguments = f'outcome="{analysis_outcome}", order_by="score"'
        outcome_analysis_step = (
            f"Sample `{analysis_outcome}` outcomes with `sample_eval_results({analysis_sample_arguments})`, then inspect "
            "the user messages in those generations."
        )
        sentiment_guidance_section = (
            "\n## How to analyze sentiment\n\n"
            "This is a sentiment evaluation. The point of this report is to help the reader understand **who is "
            "frustrated and why**, grounded in what users actually said.\n\n"
            "- **Use user messages instead of reasoning.** Sentiment is produced by a classifier, not a judge, so it "
            "has no per-result explanation. The result tools omit reasoning for this evaluation.\n"
            "- **Read what the user said instead.** Sentiment classifies only the **last user message** in each "
            "generation's input. To understand a negative result, load the generation itself (`sample_generation_details`, "
            "then `get_generation_detail` or `get_generation_text_repr`) and look at that last user message. That is "
            "where the frustration is.\n"
            "- **Start with the highest-confidence negative results.** "
            '`sample_eval_results(outcome="negative", order_by="score")` returns negative results from highest to lowest '
            "score. Sample enough results to find recurring themes in what users are complaining about, then cite "
            "representative examples.\n"
            "- Ground every claim about frustration in the user's own words. Quote or closely paraphrase the actual "
            "last user message from real negative generations you cited.\n"
        )
    elif output_type == "boolean":
        evaluated_unit = "trace" if evaluation_target == "trace" else "generation"
        result_semantics = (
            f"The evaluation returns a boolean. True means the {evaluated_unit} satisfied the configured criteria and false "
            "means it did not. A fail is not inherently bad: always interpret pass and fail through the evaluation's "
            "specific criteria rather than treating them as generic quality verdicts."
        )
        analysis_outcome = "fail"
        primary_outcome = "pass"
        reasoning_tool_section = (
            "- **`get_top_outcome_reasons(outcome, limit)`**: grouped reasoning strings for one outcome. "
            f"If omitted, outcome defaults to `{analysis_outcome}`.\n"
        )
        result_overview_detail = "Includes truncated reasoning."
        sample_ordering_signature = ""
        sample_ordering_instruction = 'Rows include full reasoning. Use the default `order_by="recent"`.'
        analysis_sample_arguments = f'outcome="{analysis_outcome}"'
        outcome_analysis_step = (
            f"Inspect grouped reasons and sample relevant outcomes, using `{analysis_outcome}` and `{primary_outcome}` "
            "as starting points."
        )
    else:
        raise ValueError(f"Unsupported evaluation report output type: {output_type}")

    if evaluation_target == "trace":
        citation_tool_instruction = (
            "call for every trace you discuss, with an empty `generation_id`. "
            "Always call `sample_trace_details` first to verify the trace."
        )
        detail_tools_section = (
            "- **`sample_trace_details(trace_ids)`**: canonical, bounded renderings for up to 10 traces. "
            "Call this before citing.\n"
            "- **`get_trace_detail(trace_id)`**: a longer canonical rendering for one trace."
        )
        grounding_rule = f"""For every recurring outcome pattern or quality issue you describe:

1. Call `sample_eval_results({analysis_sample_arguments})` to find candidate trace IDs. Sample `{primary_outcome}` as contrast when useful.
2. Call `sample_trace_details(trace_ids)` to inspect the actual traces.
3. Call `add_citation(generation_id=\"\", trace_id=trace_id, reason=reason)` for each example you use.
4. Reference the trace ID inline with single backticks so the renderer can link it.

If a trace cannot be resolved, try another example. If none resolve, report the data-quality limitation."""
        detail_step = "Call `sample_trace_details(...)` on 3-5 useful examples."
    elif evaluation_target == "generation":
        citation_tool_instruction = (
            "call for every example you discuss. Always call `sample_generation_details` first to verify the "
            "generation and get its `trace_id`."
        )
        detail_tools_section = (
            "- **`sample_generation_details(generation_ids)`**: generation data including input, output, model, "
            "tokens, and trace ID. Call this before citing.\n"
            "- **`get_generation_detail(generation_id)`**: complete data for one generation and its evaluation "
            "results.\n"
            "- **`get_generation_text_repr(generation_id)`**: canonical rendering for a generation."
        )
        grounding_rule = f"""For every recurring outcome pattern or quality issue you describe:

1. Call `sample_eval_results({analysis_sample_arguments})` to find candidate generation IDs. Sample `{primary_outcome}` as contrast when useful.
2. Call `sample_generation_details(generation_ids)` to inspect the actual input and output and obtain each trace ID.
3. Call `add_citation(generation_id, trace_id, reason)` for each example you use.
4. Reference the generation ID inline with single backticks so the renderer can link it.

If a generation cannot be resolved, try another example. If none resolve, report the data-quality limitation."""
        detail_step = "Call `sample_generation_details(...)` on 3-5 useful examples."
    else:
        raise ValueError(f"Unsupported evaluation target: {evaluation_target}")

    outcome_options = "|".join(f'"{outcome}"' for outcome in definition.outcomes)
    return EVAL_REPORT_SYSTEM_PROMPT.format(
        evaluation_name=evaluation_name,
        evaluation_description_section=description_section,
        evaluation_type=evaluation_type,
        evaluation_target=evaluation_target,
        evaluation_prompt_section=prompt_section,
        result_semantics=result_semantics,
        sentiment_guidance_section=sentiment_guidance_section,
        period_start=period_start,
        period_end=period_end,
        report_prompt_guidance_section=guidance_section,
        max_sections=MAX_REPORT_SECTIONS,
        outcome_options=outcome_options,
        reasoning_tool_section=reasoning_tool_section,
        result_overview_detail=result_overview_detail,
        sample_ordering_signature=sample_ordering_signature,
        sample_ordering_instruction=sample_ordering_instruction,
        outcome_analysis_step=outcome_analysis_step,
        citation_tool_instruction=citation_tool_instruction,
        detail_tools_section=detail_tools_section,
        grounding_rule=grounding_rule,
        detail_step=detail_step,
    )
