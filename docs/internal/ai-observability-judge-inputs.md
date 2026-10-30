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

Online trace and session evaluations run as project workflows. Their event reads include all
properties regardless of default, role, or member property access rules and AI observability
product access. Evaluation previews and interactive trace/session queries continue to apply
the requesting user's permissions.

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
They reserve space for the complete output, then sample input and tool definitions into the remaining space within the 150,000-character limit.
If the output and section labels alone exceed that limit, the run is skipped with reason `generation_output_too_long` without calling the judge.
An exception applies when the judge sees images (the `llm-analytics-judge-images` flag is on and the evaluation does not turn attachments off).
Then each image becomes an `[image N]` marker and each PDF a `[file N]` marker instead of its base64 or link, so an output with large inline attachments can fit and the run continues.
The attachment labels sent next to the transcript sit outside the 150,000-character limit, but they are bounded: at most 20 attachments, plus one summary line for the rest.
PDFs reach only OpenAI, Anthropic and Gemini judges, up to 10 MB each.
WAV and MP3 audio becomes an `[audio N]` marker and reaches Gemini judges and OpenAI audio models, always inline.
Attachments a judge can't read take none of its 20 slots, and one summary line counts them.

Generation evaluation and LLM tagger user prompts repair UTF-16 surrogate sequences after sampling.
Lone surrogates become replacement characters (`�`), while valid pairs become their Unicode character.

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
The evaluation editor separates **Judge method** from **Model**. Choose **LLM with explanation** for chat completions or **Decision model** for typed decisions.
Each method lists models with the corresponding capability from the project's saved provider connections. API keys stay in AI provider settings.
Switching methods keeps a compatible model and its saved connection; an incompatible model is cleared without changing the criteria or output settings.
Leaving decision judging for LLM judging or Hog resets an invalid threshold to its default and preserves valid thresholds.
Changing the judge method marks the evaluation as edited, including when the selected model supports both methods.
The selection is stored as `evaluation_config.judge_method` (`llm` or `decision`). Evaluations without this field keep automatic routing until a method or model is explicitly selected.
Automatic OpenRouter routing selects decisions only for models without text output. Models supporting both methods keep chat routing unless decisions are explicitly selected.
Prompt-only `evaluation_config` PATCH requests preserve the saved method; an explicit `judge_method: null` restores automatic routing.
The detail editor PATCHes only changed fields on existing evaluations. Re-enabling an evaluation or changing its model or output configuration still validates decision access.
Explicit method selection requires a selected model, including for legacy evaluations that use the project's default connection.
Projects use their saved provider keys or configure a System One-compatible deployment and its authentication.
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
Models without text output are excluded from the playground and tagger model pickers. Models supporting both text and decisions remain available for both judge methods and for chat.
The catalogue refreshes hourly and keeps its last successful response when a refresh fails, retrying refreshes after one minute.
For projects with this flag enabled, an unavailable catalogue makes automatically routed OpenRouter runs retry only when no successful response is cached.
Automatic routing and explicit decision selection also need the catalogue when changing a model or output configuration, changing the evaluation type, enabling an evaluation, or changing the judge method.
Explicit LLM judging uses chat completions without a routing catalogue lookup, including for models supporting both methods.
Renaming or disabling an evaluation does not require the catalogue.
With the flag off or unavailable, cached decision-only models skip their runs without calling either API or disabling the evaluation.
Other OpenRouter models keep the existing chat path without a catalogue refresh. If a failed chat call identifies a decision model, that run also skips without disabling the evaluation.
An out-of-credits response disables the evaluation and marks its provider key as failing, as on the chat path.
Native OpenAI decisions appear under an existing **OpenAI** key when this flag is enabled.
Select **Decision model** and `gpt-6-luna` to call OpenAI's fixed `https://api.openai.com/v1/decisions` endpoint.
OpenAI currently documents this model for Decisions; endpoint support is declared separately from the curated chat-model list.
Existing OpenAI evaluations without an explicit judge method continue using chat, including models supporting both APIs.
No custom endpoint or additional connection is required. OpenAI-compatible and Azure connections do not use this native endpoint.
The adapter translates the shared evaluation questions into OpenAI's `predicate`, `choice`, and `score` formats and validates answers by question name.
Single-selection categorical evaluations need at least two options; multiple selection still uses one predicate per option.
Numeric scores use the same ten-level rubric and full-precision mapping to configured bounds described below.
OpenAI refusals skip the run. Temporary rate limits and overload responses honor `Retry-After`, and transport failures, redirects, and server errors retry without invalidating the key.
Invalid credentials, missing model access, and exhausted quota use the existing terminal-error handling.
Native OpenAI requests use the shared DNS-pinned transport with a 60-second total deadline covering connection setup, response headers, and the body. Expired requests close their connections.
Responses are limited to 1 MiB and must be uncompressed. Redirects and SDK retries are disabled; Temporal owns retries.

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
A probability at or above `output_config.decision_threshold` produces `true`; the evaluation's existing pass/fail polarity still applies.
The threshold accepts finite numbers from 0 to 1, inclusive, and defaults to 0.5 when omitted or null.
For boolean judges, selecting **Decision model** shows **Decision threshold** as a percentage inside the **Judge model** section, below the model selector.
Changing the threshold affects new runs only; historical verdicts remain unchanged.
The raw probability is stored in `$ai_evaluation_probability` when the criteria apply, with available token usage and the configured model ID.
Missing or invalid token counts remain unknown and do not discard a valid answer.
Ingestion estimates cost from the configured model and token usage when the model appears in the existing pricing catalog.
Models without a catalog match retain their usage with cost left unknown.
A custom deployment reporting a recognized model name can inherit that model's catalog estimate; this does not measure its hosting cost.

Evaluations that allow N/A send a separate Noul question about whether the criteria apply, using the 0.5 threshold.
The instructions ask the judge to follow the evaluation prompt's N/A rules and treat missing essential context or evidence as not applicable.
A judgeable failure remains applicable; the question tells the judge not to invent missing facts.
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
See OpenAI's [Decisions guide](https://developers.openai.com/api/docs/guides/decisions), OpenRouter's [Decisions API reference](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request), and TypeSafe's [API reference](https://docs.typesafe.ai/api) for their question and answer formats.

## Reasoning level

LLM judges on Anthropic and OpenAI reasoning models can set a reasoning level with the brain button next to the model selector.
The level is stored as `evaluation_config.reasoning_level` (`minimal`, `low`, `medium` or `high`). Without it, the judge uses the model's default.
Decision models and other providers do not support it, and the API rejects a level for them.
Prompt-only `evaluation_config` PATCH requests preserve the saved level; an explicit `reasoning_level: null` restores the model default.
Selecting a model without reasoning support clears the level in the editor.

Anthropic models before Claude 4.6 get a thinking budget of 1,024, 2,048, 4,096 or 8,192 tokens. Newer models get adaptive thinking with that effort, and `minimal` becomes `low`.
OpenAI models get `reasoning_effort`. Only the original GPT-5 models accept `minimal`; other models get `low` instead.
For Anthropic, the token limit of the reply grows by the thinking budget of the level, so the verdict still fits after the thinking.

## Model output limits

When the judge reply reaches the model's output limit, the evaluation skips that item with `output_limit_exceeded`.
For Anthropic structured replies, `stop_reason="max_tokens"` triggers this skip before JSON parsing.
Historical runs still include these items, as they do for `unparsable_response`, because neither skip produces a verdict.
Users do not need to include items that already have a result to retry them.

A provider rejection of an invalid token setting does not count as a truncated reply.
The playground keeps the provider's explanation so users can correct the setting before trying again.

## Backfill recovery

Estimates and new backfills clamp their start to UTC midnight 29 days before the current UTC date.
This excludes the calendar day whose AI payloads have expired under the 30-day retention policy.
Ranges ending at or before that boundary are rejected.
Existing backfills keep their stored windows; **Retry remaining** applies the boundary when it creates a new backfill.

Generation references get up to three lookup attempts.
A final miss for a backfill reference records the evaluation as skipped with `generation_not_found`, emits no `$ai_evaluation` event, and reports no exception to error tracking.
Live references marked `awaiting_ingestion` wait 15 seconds between misses and still report the final miss.

A backfill that stops on its own shows as **Interrupted**, with a stop reason.
A backfill a user stops shows as **Cancelled**.
Backfills read a page of units (500 by default, bounded between 1 and 1,000) and wait for every outcome before advancing progress.
A backfill runs at most 16 evaluations at once (`LLMA_EVAL_BACKFILL_MAX_IN_FLIGHT`).
A run holds one of the shared ClickHouse slots only while it reads its unit, and spends most of its time waiting on the judge.
Lower the setting if backfills crowd out live evaluations.
Backfill activities retry temporary database, DNS, connection, and rate-limit failures up to 5 times within 10 minutes, or within the live time limit when that is longer, with backoff from 10 seconds to one minute.
A backfill run that still hits a DNS failure on its last attempt fails instead of recording a skip, so **Retry remaining** can run it again.
After 10 failed runs in a row, the backfill pauses for 1, 2, 5, 10, then 30 minutes, and a success resets that sequence.
The failure count and the pauses carry over between pages.
When the pauses run out, or a run reports an error that disables the evaluation, the backfill stops as **Interrupted** and keeps its cursor.
Its stop reason says whether the evaluation was disabled or the runs kept failing.
Live evaluation retry budgets remain unchanged.
Authentication, quota, blocked-endpoint, and permanent request errors retain their existing handling.
Result emission has a separate retry budget, so retrying emission does not repeat a completed judge call.

An interrupted backfill preserves completed results.
**Retry remaining** creates a new backfill with the original date range and filters, using the current evaluation settings.
It preserves usable existing results and retries units without usable results.
It is not available for a backfill that re-ran existing results.
A cancelled backfill still counts the runs it started before the cancel, because they finish and are billed.
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
No property-definition migration is required for numeric evaluations.

## Categorical outputs

Hog and LLM judge evaluations support categorical output for generation, trace, and session targets.

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
Categorical events always set `$ai_evaluation_applicable`.
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

Online evaluations and report result queries run as project workflows with complete event properties. Evaluation editors
are trusted to configure workflows that read properties hidden from ordinary users. Grant Evaluations editor access only
to people authorized to process the full inputs. AI Observability and Evaluations have separate RBAC settings.

Source-property rules do not automatically apply to evaluation outputs. To keep message content private:

- Keep the source-property rules and separately restrict `$ai_evaluation_reasoning`.
- Restrict `$ai_clusters` when evaluation cluster titles and descriptions may contain private content.
- For report events, restrict `$ai_report_content`, `$ai_report_title`, and `$ai_report_citations`.
- If outcomes are also sensitive, restrict `$ai_evaluation_result`, `$ai_evaluation_numeric_result`, and
  `$ai_evaluation_categorical_result`. Apply separate rules to sentiment properties when using sentiment evaluations.
- Restrict Evaluations viewer access to the intended report audience. Stored report API responses follow evaluation RBAC;
  property rules on report events protect the event copy, not the stored report narrative.
- Choose report email recipients and Slack channels with the same audience in mind. Deliveries contain report text and do
  not check each recipient's PostHog property permissions.
- Evaluation-report Inbox summaries are suppressed when the project has any event-property denial or a denial of access
  to the evaluation, including default, member, and role rules. Inbox copies cannot enforce those source permissions.

User-facing event queries continue to apply the configured property rules. Background report queries can read evaluation
results even when the project's default rules hide those result properties from users.
Report agents also read complete source conversations when inspecting trace or session evaluation results.

The evaluation's Runs tab defaults to the last seven days.
Its date filter applies to both the run list and summary statistics, supports custom ranges and All time, and is preserved in the URL.
Opening a specific backfill shows all runs from that backfill, regardless of the date filter.
Backfilled results use the original generation's timestamp.

Removing a numeric or categorical evaluation's passing rule stops new report generation and scheduled delivery.
Existing reports remain accessible through the Reports tab and the report list, detail, and history API endpoints.

The report agent's `list_all_eval_results` and `sample_eval_results` tools cap each response at 30,000 characters.
Large results reduce the number of examples returned; each returned example keeps its complete category list.
The tools indicate when examples are omitted, and aggregate counts and pass rates still cover the full period.

The report agent's `sample_generation_details` tool keeps the beginning and end of input and input-state previews within 500 characters, with an elision marker.
Each sample includes `input_length`, the stored input's character count before shortening the preview.
Both sampled and full generation details include input, output, cache-read, and cache-creation token counts.
The agent must inspect full generation details before claiming captured input is truncated or instrumentation is broken, and report a limitation only when those details confirm it.
Shortened previews and low input token counts alongside high cache-read or cache-creation token counts are expected and alone do not justify an auditability caveat.
A trace can contain many generations by design; use generation IDs to distinguish individual calls.
The agent must recheck these caveats from prior reports against current full generation details and omit caveats that the data does not support.

## Browser compatibility

The evaluations list keeps supported rows visible if the API returns an output type the browser cannot display.
A refresh message explains that some evaluations are omitted.
Deploy this compatibility behavior before enabling creation of a new evaluation output type.
