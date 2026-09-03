---
name: exploring-llm-evaluations
description: >
  Investigate AI observability evaluations — `hog` (deterministic code-based),
  `llm_judge` (LLM-prompt-based), and `sentiment` (user-message sentiment).
  Find existing evaluations, inspect their configuration, run them against
  specific generations, query individual results, and set up scheduled reports
  on an evaluation.
  Use when the user asks to debug why an evaluation is failing, surface common
  failure modes, compare results across filters, dry-run a Hog evaluator,
  prototype a new LLM-judge prompt, inspect sentiment classifications, or manage
  the evaluation lifecycle.
---

# Exploring AI observability evaluations

PostHog evaluations score `$ai_generation` events. Each evaluation is one of three
types:

- **`hog`** — deterministic Hog code that returns `true`/`false` (and optionally N/A).
  Best for objective rule-based checks: format validation (JSON parses, schema matches),
  length limits, keyword presence/absence, regex patterns, structural assertions, latency
  thresholds, cost guards. Cheap, fast, reproducible — no LLM call per run. Prefer this
  when the criterion can be expressed as code.
- **`llm_judge`** — an LLM scores generations against a prompt you write. Best for
  subjective or fuzzy checks: tone, helpfulness, hallucination detection, off-topic
  drift, instruction-following. Costs an LLM call per run and requires AI data
  processing approval at the org level.
- **`sentiment`** — classifies sentiment from user messages on each matching
  generation. Returns a sentiment label and score, not a pass/fail verdict.

Results from all types land in ClickHouse as `$ai_evaluation` events. Boolean
evaluations (`llm_judge` and `hog`) set `$ai_evaluation_result`; sentiment
evaluations set `$ai_sentiment_*` properties instead.

This skill covers the full lifecycle: list/inspect/manage evaluation configs, run
them on specific generations, query individual results, and configure evaluation
reports that summarize recent runs on a schedule.

## Tools

| Tool                                      | Purpose                                                        |
| ----------------------------------------- | -------------------------------------------------------------- |
| `posthog:llma-evaluation-list`            | List/search evaluation configs (filter by name, enabled flag)  |
| `posthog:llma-evaluation-get`             | Get a single evaluation config by UUID                         |
| `posthog:llma-evaluation-create`          | Create a new `llm_judge`, `hog`, or `sentiment` evaluation     |
| `posthog:llma-evaluation-update`          | Update an existing evaluation (name, prompt, enabled, …)       |
| `posthog:llma-evaluation-delete`          | Soft-delete an evaluation                                      |
| `posthog:llma-evaluation-run`             | Run an evaluation against a specific `$ai_generation` event    |
| `posthog:llma-evaluation-test-hog`        | Dry-run Hog source against recent generations (no save)        |
| `posthog:llma-evaluation-report-list`     | List the report configs attached to an evaluation              |
| `posthog:llma-evaluation-report-create`   | Schedule an AI report on an evaluation (email or Slack)        |
| `posthog:llma-evaluation-report-run-list` | Past report runs, including the report content that was sent   |
| `posthog:execute-sql`                     | Ad-hoc HogQL over `$ai_evaluation` events                      |
| `posthog:query-llm-trace`                 | Drill into the underlying generation that an evaluation scored |

All `llma-evaluation-*` tools are defined in `products/ai_observability/mcp/tools.yaml`.

## Event schema

Every run of an evaluation emits an `$ai_evaluation` event. Key properties:

| Property                     | Meaning                                                         |
| ---------------------------- | --------------------------------------------------------------- |
| `$ai_evaluation_id`          | UUID of the evaluation config                                   |
| `$ai_evaluation_name`        | Human-readable name                                             |
| `$ai_target_event_id`        | UUID of the `$ai_generation` event being scored                 |
| `$ai_trace_id`               | Parent trace ID (for jumping to the trace UI)                   |
| `$ai_evaluation_result_type` | Result kind: `boolean` or `sentiment`                           |
| `$ai_evaluation_result`      | For boolean evaluations: `true` = pass, `false` = fail          |
| `$ai_evaluation_reasoning`   | Free-text explanation (set by the LLM judge or Hog code)        |
| `$ai_evaluation_applicable`  | `false` when the evaluator decided the generation is N/A        |
| `$ai_sentiment_label`        | For sentiment evaluations: `positive`, `neutral`, or `negative` |
| `$ai_sentiment_score`        | Confidence score for the winning sentiment label                |

When `$ai_evaluation_applicable = false`, the run counts as N/A regardless of `$ai_evaluation_result`.
For evaluations that don't support N/A, this property may be `null` — treat null as "applicable".

## Workflow: investigate why an evaluation is failing

Works the same way for boolean `llm_judge` and `hog` evaluations — the differences
only matter when you eventually go to fix the evaluator (edit the prompt vs. edit
the Hog source). Sentiment evaluations should be inspected by sentiment label and
score rather than pass/fail filters.

### Step 1 — Find the evaluation

```json
posthog:llma-evaluation-list
{ "search": "hallucination", "enabled": true }
```

Look at the returned `id`, `name`, `evaluation_type`, and either:

- `evaluation_config.prompt` for an `llm_judge`
- `evaluation_config.source` for a `hog` evaluator

The Hog source is the ground truth for why a hog evaluator passes or fails — read it
before assuming the failure is in the generation.

### Step 2 — Break down pass, fail, and N/A

```sql
posthog:execute-sql
SELECT
    countIf(properties.$ai_evaluation_applicable = false) AS na_count,
    countIf(
        (properties.$ai_evaluation_applicable IS NULL
            OR properties.$ai_evaluation_applicable != false)
        AND properties.$ai_evaluation_result = true
    ) AS pass_count,
    countIf(
        (properties.$ai_evaluation_applicable IS NULL
            OR properties.$ai_evaluation_applicable != false)
        AND properties.$ai_evaluation_result = false
    ) AS fail_count
FROM events
WHERE event = '$ai_evaluation'
    AND properties.$ai_evaluation_id = '<evaluation_uuid>'
    AND timestamp >= now() - INTERVAL 7 DAY
```

If the evaluation already has report configs, `llma-evaluation-report-list` and
`llma-evaluation-report-run-list` give you the AI-written reports from earlier
periods, which is a fast way to see how the picture has moved.

### Step 3 — Read the failing runs

The reasoning text is where the pattern shows up. Pull the recent fails and read
them:

```sql
posthog:execute-sql
SELECT
    properties.$ai_target_event_id AS generation_id,
    properties.$ai_trace_id AS trace_id,
    properties.$ai_evaluation_reasoning AS reasoning,
    timestamp
FROM events
WHERE event = '$ai_evaluation'
    AND properties.$ai_evaluation_id = '<evaluation_uuid>'
    AND properties.$ai_evaluation_result = false
    AND (
        properties.$ai_evaluation_applicable IS NULL
        OR properties.$ai_evaluation_applicable != false
    )
    AND timestamp >= now() - INTERVAL 7 DAY
ORDER BY timestamp DESC
LIMIT 25
```

The N/A guard (`IS NULL OR != false`) is important — it matches the same logic the
backend uses to bucket runs.

### Step 4 — Drill into example failing runs

Take the most representative rows from Step 3 and pull the underlying trace:

```json
posthog:query-llm-trace
{ "traceId": "<trace_id>", "dateRange": {"date_from": "-30d"} }
```

(If you only have a generation ID, query for it via `execute-sql` first to find the
parent trace ID.)

## Workflow: run an evaluation against a specific generation

Use this when the user pastes a trace/generation URL and asks "what would evaluation X
say about this?".

```json
posthog:llma-evaluation-run
{
  "evaluationId": "<eval_uuid>",
  "target_event_id": "<generation_event_uuid>",
  "timestamp": "2026-04-01T19:39:20Z",
  "event": "$ai_generation"
}
```

The `timestamp` is required for an efficient ClickHouse lookup of the target event.
Pass `distinct_id` if you have it — it speeds up the lookup further.

## Workflow: build and test a new evaluator

### Hog evaluator (deterministic, code-based)

Reach for this first when the criterion is rule-based — it's cheaper, faster, and
reproducible. Prototype with `llma-evaluation-test-hog` (no save):

```json
posthog:llma-evaluation-test-hog
{
  "source": "return event.properties.$ai_output_choices[1].content contains 'sorry';",
  "sample_count": 5,
  "allows_na": false
}
```

The handler returns the boolean result for each of the most recent N `$ai_generation`
events. Iterate on the source until it behaves as expected, then promote it via
`llma-evaluation-create`:

```json
posthog:llma-evaluation-create
{
  "name": "Output is valid JSON",
  "description": "Fails when the assistant message can't be parsed as JSON",
  "evaluation_type": "hog",
  "evaluation_config": {
    "source": "let raw := event.properties.$ai_output_choices[1].content; try { jsonParseStr(raw); return true; } catch { return false; }"
  },
  "output_type": "boolean",
  "enabled": true
}
```

Hog evaluators have full access to the event and its properties — common patterns
include schema validation, length/token limits, regex matches, and tool-call shape
checks. Because they're deterministic, results are reproducible across reruns and
trivially diff-able.

### LLM-judge evaluator (subjective, prompt-based)

Use this when the criterion is fuzzy and a code rule would be brittle (tone, factuality,
helpfulness, on-topic-ness). There's no equivalent of `llma-evaluation-test-hog` for LLM
judges — the typical loop is to create the evaluator with `enabled: false`, run it
manually against a handful of representative generations via `llma-evaluation-run`, inspect
the results, refine the prompt with `llma-evaluation-update`, and then flip `enabled: true`
when you're satisfied:

```json
posthog:llma-evaluation-create
{
  "name": "Response stays on-topic",
  "description": "LLM judge — fails if the assistant changes topic from the user's question",
  "evaluation_type": "llm_judge",
  "evaluation_config": {
    "prompt": "You are evaluating whether the assistant's reply stays on-topic relative to the user's most recent question. Return true if it does, false if the assistant changed the subject. Return N/A if the user did not actually ask a question."
  },
  "output_type": "boolean",
  "output_config": { "allows_na": true },
  "model_configuration": {
    "provider": "openai",
    "model": "gpt-5-mini"
  },
  "enabled": false
}
```

Then dry-run against a known-good and a known-bad generation:

```json
posthog:llma-evaluation-run
{
  "evaluationId": "<new_eval_uuid>",
  "target_event_id": "<generation_uuid>",
  "timestamp": "2026-04-01T19:39:20Z"
}
```

LLM judges require organisation AI data processing approval. Hog evaluators do not.

## Workflow: manage the evaluation lifecycle

| Action                     | Tool                                                                                                                  |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Add a Hog evaluator        | `llma-evaluation-create` with `evaluation_type: "hog"` and `evaluation_config.source`                                 |
| Add an LLM-judge evaluator | `llma-evaluation-create` with `evaluation_type: "llm_judge"`, `evaluation_config.prompt`, and a `model_configuration` |
| Tweak the source or prompt | `llma-evaluation-update` (edits `evaluation_config.source` for Hog, `evaluation_config.prompt` for LLM judge)         |
| Toggle N/A handling        | `llma-evaluation-update` with `output_config.allows_na`                                                               |
| Disable temporarily        | `llma-evaluation-update` with `enabled: false`                                                                        |
| Remove                     | `llma-evaluation-delete` (soft-delete via PATCH `{deleted: true}`)                                                    |

`llm_judge` evaluations require AI data processing approval at the org level
(`is_ai_data_processing_approved`). Hog evaluations do **not** require this gate
— they run as plain code on the ingestion pipeline.

## When to use Hog vs LLM judge

Reach for **Hog** by default. Switch to LLM judge only when the criterion can't be
expressed as code.

| Use Hog when…                                         | Use LLM judge when…                                     |
| ----------------------------------------------------- | ------------------------------------------------------- |
| The check is structural (JSON parses, schema matches) | The check is about meaning (on-topic, helpful, factual) |
| You need a deterministic, reproducible result         | A small amount of judgement variability is acceptable   |
| The criterion is cheap to compute                     | The criterion requires reading and understanding text   |
| You can't get AI data processing approval             | You have approval and the criterion is genuinely fuzzy  |
| You need to enforce a hard limit (length, cost, etc.) | You need to rate a quality dimension                    |
| You want sub-millisecond evaluation                   | A few hundred milliseconds + LLM cost are acceptable    |

A common pattern is to **layer them**: a Hog evaluator gates obvious format/length
violations cheaply, and an LLM-judge evaluator only fires on the generations that pass
the Hog gate (via `conditions`).

## Investigation patterns

Diagnosis works the same way regardless of whether the evaluator is `hog` or
`llm_judge` — you read the resulting `$ai_evaluation` events, not the evaluator itself.
The fix path differs (edit Hog source vs. edit prompt) but the diagnosis is
identical.

### "Why is evaluation X suddenly failing more?"

1. `llma-evaluation-list` — confirm the evaluation is still enabled and unchanged
   (compare `evaluation_config.source` or `evaluation_config.prompt` to the version you
   expect)
2. Read the recent failing runs and their reasoning (Step 3 above) and group them
   into the dominant failure patterns
3. SQL count of fails per day to confirm the regression window:

   ```sql
   SELECT toDate(timestamp) AS day, count() AS fails
   FROM events
   WHERE event = '$ai_evaluation'
       AND properties.$ai_evaluation_id = '<uuid>'
       AND properties.$ai_evaluation_result = false
       AND timestamp >= now() - INTERVAL 30 DAY
   GROUP BY day
   ORDER BY day
   ```

4. Drill into a representative trace per pattern via `query-llm-trace`

### "Are passes and fails caused by the same root content?"

1. Pull two samples with the Step 3 query, flipping `$ai_evaluation_result` between
   `true` and `false`
2. If the passing and failing runs describe similar content:
   - For an `llm_judge`: the prompt or rubric is probably ambiguous — reword
     `evaluation_config.prompt` and use `llma-evaluation-update`
   - For a `hog` evaluator: the rule is probably under- or over-matching — read the
     source via `llma-evaluation-get`, narrow the predicate, and retest with
     `llma-evaluation-test-hog` before pushing the fix via `llma-evaluation-update`

### "Did a Hog evaluator regression after a code change?"

Hog evaluators are reproducible — if the source hasn't changed, identical inputs should
yield identical outputs. When fail rates jump for a Hog evaluator:

1. `llma-evaluation-get` — note the current source and `updated_at`
2. Spot-check the latest failing runs with the SQL query from Step 4 above
3. Re-run the source against those exact generations using `llma-evaluation-test-hog` with a
   modified `conditions` filter that targets them
4. If the test results match the live results, the change is in the _generations_, not
   the evaluator (a model upgrade, prompt change upstream, etc.) — investigate the
   producer
5. If they diverge, the evaluator was edited; check git history of the source field via
   the activity log

### "What kinds of generations does this evaluator skip as N/A?"

```sql
posthog:execute-sql
SELECT
    properties.$ai_target_event_id AS generation_id,
    properties.$ai_trace_id AS trace_id,
    properties.$ai_evaluation_reasoning AS reasoning,
    timestamp
FROM events
WHERE event = '$ai_evaluation'
    AND properties.$ai_evaluation_id = '<evaluation_uuid>'
    AND properties.$ai_evaluation_applicable = false
    AND timestamp >= now() - INTERVAL 7 DAY
ORDER BY timestamp DESC
LIMIT 25
```

Read the reasoning on those runs to see whether the N/A logic is doing the right
thing. If a run looks like something that should have been scored:

- For an `llm_judge`: the applicability instruction in the prompt is too broad — narrow
  it
- For a `hog` evaluator with `output_config.allows_na: true`: the source is returning
  `null` (or whatever the N/A signal is) too eagerly — tighten the precondition

### "Score this single generation right now"

`llma-evaluation-run` with the trace's generation ID and timestamp. Useful for spot-checking
or wiring evaluations into a larger agent loop.

## Constructing UI links

- **Evaluations list**: `https://app.posthog.com/ai-evals/evaluations`
- **Single evaluation**: `https://app.posthog.com/ai-evals/evaluations/<evaluation_id>`
- **Underlying generation/trace**: see the `exploring-llm-traces` skill's URL conventions

Always surface the relevant link so the user can verify in the UI.

## Tips

- Evaluation reports are configured per evaluation with `llma-evaluation-report-create`:
  `frequency: "scheduled"` with an `rrule` for a daily or weekly cadence, or
  `frequency: "every_n"` with a `trigger_threshold` to fire once that many new results
  have accumulated. Delivery goes to email or Slack via `delivery_targets`
- `llma-evaluation-report-generate` runs a configured report immediately instead of
  waiting for the next trigger; `llma-evaluation-report-run-list` returns past runs with
  the report content they delivered
- For rich filtering not supported by `llma-evaluation-list` (e.g. by author or model
  configuration), fall back to `execute-sql` against the `evaluations` Postgres table or
  the `$ai_evaluation` ClickHouse events
- When showing failure patterns to the user, always include 1-2 example trace links so
  they can validate the pattern visually
- `llma-evaluation-*` tools use `evaluation:read` for read tools and `evaluation:write` for
  mutating tools; the `llma-evaluation-report-*` tools use `llm_analytics:read` and
  `llm_analytics:write`
- Hog evaluators are reproducible — if you suspect a regression, `llma-evaluation-test-hog`
  with the suspect source against the failing generations is the fastest way to bisect
  whether the change is in the evaluator or in the producer of the generations
- LLM-judge evaluators are non-deterministic across reruns; expect 1-5% noise even with
  a fixed prompt and model. If you're chasing a small regression in fail rate, prefer
  Hog or pin a deterministic provider/seed in the `model_configuration`

## Related skills

- **`creating-online-evaluations`** — author a new evaluation from scratch
- **`exploring-ai-failures`** — ground the next evaluation in observed failure modes
