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
Deploy the ingestion and evaluation worker changes before enabling the flag.
Projects configure a System One-compatible deployment and its authentication.
Evaluation connections never fall back to an instance credential or gateway configuration.
PostHog's regional AI gateway endpoints additionally require an organization in `POSTHOG_INTERNAL_ORG_IDS`; customer projects cannot use those endpoints.
Connection validation and every evaluation check these gates; an absent flag or failed flag lookup blocks the call.
Turning the flag off stops subsequent runs, including queued work, without disabling the saved evaluation.
Keep the experimental flag limited to staff projects during rollout.
Add a connection under **System One** in provider key settings.
Enter the public HTTPS base URL and model ID of a compatible service; neither has a default.
TypeSafe's hosted endpoint is not supported by this integration.
The client appends `/systemone` to the base URL and sends the API key as a bearer token.
An empty key selects no authentication.
Changing the endpoint requires entering its credential again, or explicitly choosing no authentication, so an existing key is not forwarded to a new host.
Private network destinations and redirects are blocked by the shared DNS-pinned HTTP transport.
Saving a connection validates it with a short synthetic input and a Noul question, without sending evaluation data, using a 10-second request timeout.
System One connections opt into the shared HTTPX client's bounded transport.
Each HTTP request has a total deadline covering connection setup, response headers, and the body; expiry cancels the network operation and closes the connection.
Validation uses 10 seconds and System One evaluations use 60 seconds.
The transport rejects response bodies above 1 MiB, including errors.
It requests uncompressed responses and rejects compressed responses to prevent decompression from bypassing the size limit.
Responses stream incrementally, with a separate connection per request; connections are not pooled across requests.
Select the connection and configured model on each evaluation; these connections cannot become the shared active provider key used by other AI features.
Provider keys keep the provider they were created with; switching providers requires a new key.
The evaluation integration uses Noul for boolean outputs, with the same formatted text for generation, trace, and session targets.
The product client reuses the request builder and response parser in `posthog/llm/system_one.py` and constructs a DNS-pinned client from `posthog/security/pinned_httpx.py` with the bounded transport.
Customer connections do not consume PostHog's TypeSafe account budgets or emit TypeSafe egress metrics.
The selected connection supplies its own endpoint and credential; it never falls back to instance gateway settings.
Categorical evaluations use a native Choice question for single selection, with option keys mapped to their labels.
Multiple selection uses one Noul question per option and includes each category with probability at least 0.5.
The endpoint must support the configured number of options and questions; model limits can be lower than the evaluation's configuration limit.
Results use the existing categorical event property and passing rules.
An empty selection is an applicable result; N/A remains a separate outcome.
`$ai_evaluation_probability` remains the probability of true for boolean evaluations and is not emitted for categorical results.
Numeric evaluations retain their existing arbitrary ranges and completion-based judges.
API compatibility does not guarantee equivalent judgments or calibration across models.
Compare results on representative inputs when changing models.

For boolean evaluations, the prompt becomes a [Noul question](https://docs.typesafe.ai/primitives/noul).
A probability of at least 0.5 produces `true`; the evaluation's existing pass/fail polarity still applies.
The raw probability is stored in `$ai_evaluation_probability` when the criteria apply, with available token usage and the configured model ID.
Missing or invalid token counts remain unknown and do not discard a valid answer.
Ingestion estimates cost from the configured model and token usage when the model appears in the existing pricing catalog.
Models without a catalog match retain their usage with cost left unknown.
A custom deployment reporting a recognized model name can inherit that model's catalog estimate; this does not measure its hosting cost.

Evaluations that allow N/A send a separate Noul question about whether the criteria apply, using the 0.5 threshold.
Uncertainty alone does not produce N/A.
System One answers contain no written reasoning, so reports inspect the original source when explaining outcomes.

Endpoint rate limits and overload responses are retried through Temporal, honoring `Retry-After` up to one minute.
Evaluation events retain model, usage, latency, and error telemetry.
If retries fail, the run fails and the evaluation stays enabled.
Blocked endpoints and redirects disable the evaluation and mark the connection for revalidation, without recording model usage.
Requests rejected because of an individual input skip that run without changing the shared connection.
Invalid probabilities, missing answers, and mismatched answer types skip the item as an unparsable response.
Inputs rejected for exceeding the model's context window are skipped.
See TypeSafe's [API reference](https://docs.typesafe.ai/api) for the System One protocol.

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
Categorical evaluations write a list of category keys to `$ai_evaluation_categorical_result`, including for single selection.
Sentiment evaluations keep their `$ai_sentiment_*` properties.
N/A and skipped numeric runs omit the score, while zero remains a graded result.

Separate properties preserve the existing boolean property's type and saved queries.
The numeric property uses normal numeric inference and can be aggregated in Insights.
Numeric queries use `toFloat(properties.$ai_evaluation_numeric_result)` to also handle properties whose metadata has not been registered yet.
No property-definition migration is required before enabling `llm-analytics-numeric-evaluations`.

## Categorical outputs

Hog and LLM judge evaluations support categorical output for generation, trace, and session targets.
Creation is gated by `llm-analytics-categorical-evaluations`, disabled by default, in the API and frontend.
Existing evaluations remain editable and continue running when the flag is off.

The output configuration defines `options` as `{key, label}` pairs, `selection_mode` as `single` or `multiple`, and optional `allows_na`.
Each evaluation supports 1 to 100 categories, enforced by the API and editor.
Keys must be unique lowercase identifiers; labels are for display.
Keep keys stable when changing labels so historical results retain their meaning.
In the editor, **Categories per result** controls the number of returned categories independently of the passing rule.
Category errors appear below the category table; passing-rule errors appear below the passing categories.

Hog returns a list of keys, or a single key string for single selection.
The editor updates the untouched Hog example when its category key changes, is removed, or the draft's output type changes.
Custom code is preserved.
The LLM judge returns `categories` and `reasoning`.
Single selection requires exactly one key; multiple selection accepts `[]` as an applicable result.
Categorical events always set `$ai_evaluation_applicable`, because native JSON property reads treat empty arrays as absent.
`null` means N/A only when `allows_na` is enabled.
Unknown or duplicate keys are invalid results.
Invalid model responses and Hog results with unknown keys, duplicate keys, or the wrong number of selections skip the run without disabling the evaluation.
Wrong Hog return types follow the existing return-contract error path.

An optional `passing_rule: {categories: [key]}` marks the passing categories.
With passing categories selected, a result passes only when it contains at least one category and every returned category is marked as passing.
Single selection requires at least one passing category when a rule is enabled.
Multiple selection allows an empty passing-categories list; only `[]` passes that rule.
N/A and skipped runs are excluded from pass rates.
Run details, text representations, and report-agent generation details distinguish skipped runs from N/A, even when N/A is disabled.
Without a rule, results stay ungraded and new reports are unavailable.
Rule edits reclassify stored results, while each report retains its own configuration snapshot.

The new result property leaves boolean and numeric properties unchanged and needs no property-definition backfill.
Evaluation clustering excludes numeric and categorical results because its embedding format requires boolean verdicts.
Deploy all evaluation workers before enabling the flag.

## Run history and reports

The evaluation's Runs tab defaults to the last seven days.
Its date filter applies to both the run list and summary statistics, supports custom ranges and All time, and is preserved in the URL.
Opening a specific backfill shows all runs from that backfill, regardless of the date filter.
Backfilled results use the original generation's timestamp.

Removing a numeric or categorical evaluation's passing rule stops new report generation and scheduled delivery.
Existing reports remain accessible through the Reports tab and the report list, detail, and history API endpoints.

The report agent's `list_all_eval_results` and `sample_eval_results` tools cap each response at 30,000 characters.
Large results reduce the number of examples returned; each returned example keeps its complete category list.
The tools indicate when examples are omitted, and aggregate counts and pass rates still cover the full period.

## Browser compatibility

The evaluations list keeps supported rows visible if the API returns an output type the browser cannot display.
A refresh message explains that some evaluations are omitted.
Deploy this compatibility behavior before enabling creation of a new evaluation output type.
