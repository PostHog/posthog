# LLM judge input budgets

Online LLM-as-a-judge evaluations apply fixed character budgets to the text sent as the user prompt.
These budgets include transcript headers and line numbers, but exclude the evaluation's system prompt.
They do not change with the selected judge model.

| Target     | Character budget |
| ---------- | ---------------: |
| Generation |          150,000 |
| Trace      |          150,000 |
| Session    |          500,000 |

## Trace and session formatting

Trace and session evaluations first render a text representation with message truncation and line sampling disabled.
This attempt stops when the text exceeds the budget, before assembling the complete oversized transcript in memory.
If the complete rendered transcript fits its budget, the evaluation uses that text.
For sessions, this check includes every trace and the separators between traces, so a large trace can use space left by smaller traces.

If the transcript exceeds its budget, the evaluation retries with input history and span content truncated, while keeping generation outputs complete.
Each truncated content block retains its first 500 and last 500 characters, with a `... (X chars truncated) ...` marker in between.
This attempt also stops at the budget and does not sample lines, so a long input does not unnecessarily damage the answer being graded.
Sessions share the full budget across traces during this attempt.

If the transcript still exceeds its budget, the evaluation also truncates generation outputs and samples lines as needed.
This final fallback can omit parts of an answer. It is used only when complete outputs and shortened inputs cannot fit.
In this fallback, sessions divide their budget evenly across traces, with a minimum allocation of 2,000 characters per trace.
If the assembled fallback session still exceeds 500,000 characters, the evaluation skips it with `session_too_long_to_judge`.

## Generation formatting

Generation evaluations extract message text without the per-message character cutoff.
They sample the combined input, tool definitions, and output only when that text exceeds 150,000 characters, with a final character slice enforcing the limit.

Implementation: [trace judge](../../posthog/temporal/ai_observability/run_trace_evaluation.py), [session judge](../../posthog/temporal/ai_observability/run_session_evaluation.py), and [generation judge](../../posthog/temporal/ai_observability/evaluation_llm_judge.py).

## Model output limits

When the judge reply reaches the model's output limit, the evaluation skips that item with `output_limit_exceeded`.
For Anthropic structured replies, `stop_reason="max_tokens"` triggers this skip before JSON parsing.
Historical runs still include these items, as they do for `unparsable_response`, because neither skip produces a verdict.
Users do not need to include items that already have a result to retry them.

A provider rejection of an invalid token setting does not count as a truncated reply.
The playground keeps the provider's explanation so users can correct the setting before trying again.

## Result encoding

Boolean online evaluations write their raw verdict to `$ai_evaluation_result`.
Numeric evaluations write their score to `$ai_evaluation_numeric_result`, with optional `$ai_evaluation_numeric_result_min` and `$ai_evaluation_numeric_result_max` bounds.
`$ai_evaluation_result_type` identifies the output type; events without it are legacy boolean results.
Sentiment evaluations keep their `$ai_sentiment_*` properties.
N/A and skipped numeric runs omit the score, while zero remains a graded result.

Separate properties preserve the existing boolean property's type and saved queries.
The numeric property uses normal numeric inference and can be aggregated in Insights.
Numeric queries use `toFloat(properties.$ai_evaluation_numeric_result)` to also handle properties whose metadata has not been registered yet.
No property-definition migration is required before enabling `llm-analytics-numeric-evaluations`.

## Run history and reports

The evaluation's Runs tab defaults to the last seven days.
Its date filter applies to both the run list and summary statistics, supports custom ranges and All time, and is preserved in the URL.
Opening a specific backfill shows all runs from that backfill, regardless of the date filter.
Backfilled results use the original generation's timestamp.

Removing a numeric evaluation's passing rule stops new report generation and scheduled delivery.
Existing reports remain accessible through the Reports tab and the report list, detail, and history API endpoints.

## Browser compatibility

The evaluations list keeps supported rows visible if the API returns an output type the browser cannot display.
A refresh message explains that some evaluations are omitted.
Deploy this compatibility behavior before enabling creation of a new evaluation output type.
