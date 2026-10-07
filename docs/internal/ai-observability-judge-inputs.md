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

## OpenAI-compatible judges

Custom OpenAI-compatible connections use the shared DNS-pinned HTTPX transport with response bounds enabled.
Every completion request has a 60-second total HTTP deadline, including connection setup, response headers, and the body.
Key validation and model listing use a 10-second total deadline.
Responses, including errors and streamed completions, are limited to 1 MiB.
The endpoint must return uncompressed responses; compressed responses are rejected before decoding.
Expired requests, rejected responses, and streams closed by the caller close their underlying connection.

The OpenAI SDK does not retry custom-provider requests. Online evaluations and taggers use their existing Temporal retry policies for transient failures, and worker cancellation propagates to Temporal.
Rate-limit responses retry without disabling the evaluation or marking its connection invalid, honoring `Retry-After` up to one minute. Quota and authentication errors keep their existing terminal behavior.
Models without native structured-output support retain the JSON fallback, which can make one additional bounded request.
Oversized or compressed completion responses skip the evaluation as a rejected request without disabling the connection.
The evaluation records the response limit and how to configure the endpoint.
These connection and response limits also apply when using the same provider in the playground.
Disconnecting from the playground releases the server's stream slot without waiting for an in-flight provider read.
The worker closes the connection when that read finishes or reaches the provider's deadline.

## Decision model judges

Decision models are available under the existing LLM judge option. They return typed answers without written reasoning.
The `llm-analytics-system-one-evaluations` project-group feature flag controls access in the browser and background workers.
Both use the project's UUID as its group key; the numeric project ID is a group property.
Deploy the ingestion and evaluation worker changes before enabling the flag.
Projects configure a System One-compatible deployment and its authentication.
Evaluation connections never fall back to an instance credential or gateway configuration.
The configured endpoint authorizes the supplied credential, including connections to PostHog's regional AI gateway endpoints.
Connection validation and every evaluation check these gates; an absent flag or failed flag lookup blocks the call.
Turning the flag off stops subsequent runs, including queued work, without disabling the saved evaluation.
Keep the experimental flag limited to staff projects during rollout.
OpenRouter decision models, including Jev, appear under an existing OpenRouter key in the evaluation model picker when this flag is enabled.
They use OpenRouter's alpha `/api/alpha/decisions` endpoint with that key; no custom endpoint or System One connection is needed.
These requests send the same PostHog attribution headers as OpenRouter chat requests.
The picker discovers models through the catalogue's `decisions` output modality, so new models and versions appear without a code change.
The picker does not exclude individual decision models. Listed models may not support every evaluation output type.
The catalogue does not expose supported question types. If a model rejects a request, the run is skipped without retrying, with a reason to check output-type and criteria compatibility.
Support added by a provider works on subsequent runs without a PostHog code change.
Chat models such as Jev Router keep using chat completions.
Decision models are excluded from the playground and tagger model pickers.
The catalogue refreshes hourly and keeps its last successful response when a refresh fails, retrying refreshes after one minute.
For projects with this flag enabled, an unavailable catalogue makes OpenRouter runs retry only when no successful response is cached.
These projects also need the catalogue when changing a model or output configuration, changing the evaluation type, or enabling an evaluation.
Renaming or disabling an evaluation does not require the catalogue.
With the flag off or unavailable, cached decision models skip their runs without calling either API or disabling the evaluation.
Other OpenRouter models keep the existing chat path without a catalogue refresh. If a failed chat call identifies a decision model, that run also skips without disabling the evaluation.
An out-of-credits response disables the evaluation and marks its provider key as failing, as on the chat path.
For other compatible services, add a connection under **System One** in provider key settings.
Enter the public HTTPS base URL and model ID of a compatible service; neither has a default.
TypeSafe's hosted endpoint is not supported by this integration.
The client appends `/systemone` to the base URL and sends the API key as a bearer token.
An empty key selects no authentication.
Changing the endpoint requires entering its credential again, or explicitly choosing no authentication, so an existing key is not forwarded to a new host.
Private network destinations and redirects are blocked by the shared DNS-pinned HTTP transport.
Saving a connection validates it with a short synthetic input and a Noul question, without sending evaluation data, using a 10-second request timeout.
Decision model connections opt into the shared HTTPX client's bounded transport.
Each HTTP request has a total deadline covering connection setup, response headers, and the body; expiry cancels the network operation and closes the connection.
Validation uses 10 seconds and decision model evaluations use 60 seconds.
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
Numeric evaluations use a native Score question and require finite minimum and maximum bounds, with the minimum below the maximum.
The evaluation prompt defines the scoring criteria, including what low and high scores mean.
The judge generates ten evenly spaced reference scores across the configured range and sends them as ordered rubric levels.
The endpoint's fractional index (0–9) is mapped linearly back to that range and stored in `$ai_evaluation_numeric_result`.
Rubric descriptions preserve each reference score's full float precision; the stored numeric result is not rounded.
For example, an index of 6.75 on a 0–10 range produces 7.5. Step remains a prompt hint and does not round the result.
These are estimated ratings, not exact counts; unbounded numeric outputs still require a completion-based judge.
Numeric results use the existing passing rules and N/A handling. No new output configuration fields are required.
`$ai_evaluation_probability` remains the probability of true for boolean evaluations and is not emitted for categorical or numeric results.
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
Decision model answers contain no written reasoning, so reports inspect the original source when explaining outcomes.

Endpoint rate limits and overload responses are retried through Temporal, honoring `Retry-After` up to one minute.
Evaluation events retain model, usage, latency, and error telemetry.
If retries fail, the run fails and the evaluation stays enabled.
Blocked System One endpoints and redirects disable the evaluation and mark the connection for revalidation, without recording model usage.
DNS failures and redirects at OpenRouter's fixed decision endpoint retry without disabling the evaluation or marking its key as failing. Redirects are never followed.
DNS failures at custom System One endpoints also retry without disabling the evaluation or its key.
Requests rejected because of an individual input skip that run without changing the shared connection.
Invalid probabilities, missing answers, and mismatched answer types skip the item as an unparsable response.
Inputs rejected for exceeding the model's context window are skipped.
See OpenRouter's [Decisions API reference](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request) and TypeSafe's [API reference](https://docs.typesafe.ai/api) for their compatible question and answer formats.

## Model output limits

When the judge reply reaches the model's output limit, the evaluation skips that item with `output_limit_exceeded`.
For Anthropic structured replies, `stop_reason="max_tokens"` triggers this skip before JSON parsing.
Historical runs still include these items, as they do for `unparsable_response`, because neither skip produces a verdict.
Users do not need to include items that already have a result to retry them.

A provider rejection of an invalid token setting does not count as a truncated reply.
The playground keeps the provider's explanation so users can correct the setting before trying again.

## Backfill recovery

Backfills wait for evaluation outcomes before advancing progress and run at most four evaluations concurrently per backfill.
The existing shared ClickHouse concurrency limiter still applies across background AI observability queries.
Backfill fetch and judge activities retry temporary database, DNS, connection, and rate-limit failures for up to 30 minutes per activity.
Backoff starts at 10 seconds and increases to at most one minute; successful requests do not wait for that interval.
Live evaluation retry budgets remain unchanged.
Authentication, quota, blocked-endpoint, and permanent request errors retain their existing handling.
Result emission has a separate retry budget, so retrying emission does not repeat a completed judge call.

An interrupted backfill preserves completed results.
**Retry remaining** creates a new backfill with the original date range and filters, using the current evaluation settings.
It preserves usable existing results and retries units without usable results, including recorded DNS failures.
Persistent failures can still interrupt a backfill after its recovery budget; recovery does not guarantee a verdict for invalid or permanently rejected inputs.

## Result encoding

Boolean online evaluations write their raw verdict to `$ai_evaluation_result`.
Numeric evaluations write their score to `$ai_evaluation_numeric_result`, with optional `$ai_evaluation_numeric_result_min` and `$ai_evaluation_numeric_result_max` bounds.
Result badges and mean scores display up to two decimal places, with two significant digits for values below one to keep small nonzero scores visible. Badges in the runs table expose the exact score on hover; storage, sorting, and passing rules use the original value.
If rounding would change whether the displayed score meets the passing rule, the badge shows the exact score instead.
For online LLM judges, including decision models, `step` is a suggested score increment in the prompt; results are not rounded or restricted to its multiples.
Hog evaluations use the numeric value returned by the code and do not apply `step`.
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
