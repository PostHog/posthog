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

Trace evaluations skip the LLM judge when a trace has no child events and no readable trace-level input or output.
Message role headers, empty OpenTelemetry parts, and whitespace-only message bodies do not count as readable content.
Tool calls embedded in output content count as readable content, even when the adjacent text is whitespace.
Root-only traces with readable state still reach the judge, and Hog evaluations can grade root-only traces from their metadata.

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

## System One judges

System One-compatible models are available under the existing LLM judge option.
The `llm-analytics-system-one-evaluations` project-group feature flag controls access in the browser and background workers.
Customers configure their own TypeSafe key or a compatible deployment with its own authentication.
Evaluation connections never fall back to an instance TypeSafe key or gateway credential.
PostHog's regional AI gateway endpoints additionally require an organization in `POSTHOG_INTERNAL_ORG_IDS`; customer projects cannot use those endpoints.
Connection validation and every evaluation check these gates; an absent flag or failed flag lookup blocks the call.
Turning the flag off stops subsequent runs, including queued work, without disabling the saved evaluation.
Keep the experimental flag limited to staff projects until customer rollout meets the [TypeSafe usage policy](../../posthog/egress/typesafe/README.md#usage-policy).
Add a connection under **System One (Jev)** in provider key settings.
The default endpoint is TypeSafe's `https://api.typesafe.ai/v1`, with model `jev-1.13.0` and a TypeSafe API key.
Advanced configuration accepts a different public HTTPS base URL and model ID for compatible services.
The client appends `/systemone` to the base URL and sends the API key as a bearer token.
An empty key selects no authentication for a custom endpoint; TypeSafe requires a key.
Changing the endpoint requires entering its credential again, or explicitly choosing no authentication, so an existing key is not forwarded to a new host.
Private network destinations and redirects are blocked by the shared DNS-pinned HTTP transport.
Saving a connection validates it with a short synthetic input and a Noul question, without sending evaluation data.
Select the connection and configured model on each evaluation; these connections cannot become the shared active provider key used by other AI features.
Provider keys keep the provider they were created with; switching providers requires a new key.
The evaluation integration uses Noul for boolean outputs, with the same formatted text for generation, trace, and session targets.
The integration reuses the typed Noul client, rate limiter, and request telemetry in `posthog/egress/typesafe`.
Numeric and categorical support is separate from this integration.
Numeric evaluations retain their existing arbitrary ranges and completion-based judges.
API compatibility does not guarantee equivalent judgments or calibration across models.
Compare results on representative inputs when changing models.

For boolean evaluations, the prompt becomes a [Noul question](https://docs.typesafe.ai/primitives/noul).
A probability of at least 0.5 produces `true`; the evaluation's existing pass/fail polarity still applies.
The raw probability is stored in `$ai_evaluation_probability`, with token usage and the resolved model version.

Evaluations that allow N/A send a separate Noul question about whether the criteria apply, using the 0.5 threshold.
Uncertainty alone does not produce N/A.
System One answers contain no written reasoning, so reports inspect the original source when explaining outcomes.

Each endpoint and credential pair has a separate, hashed rate-limit scope shared across workers.
Evaluations use the batch lane; connection validation uses the normal lane.
Local budget exhaustion, rate limits, and overload responses are retried through Temporal, honoring `Retry-After` up to five minutes.
If retries fail, the run fails and the evaluation stays enabled.
Blocked endpoints and rejected requests disable the evaluation and mark the connection for revalidation, without recording model usage.
Invalid probabilities, missing answers, and mismatched answer types skip the item as an unparsable response.
Inputs rejected for exceeding the model's context window are skipped.
See TypeSafe's [API reference](https://docs.typesafe.ai/api) and [model limits and pricing](https://docs.typesafe.ai/models).

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
