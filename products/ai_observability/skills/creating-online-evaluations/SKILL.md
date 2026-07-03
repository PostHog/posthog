---
name: creating-online-evaluations
description: >
  Author continuously-running online evaluations in PostHog AI observability, grounded in a real failure
  mode you've identified. Use when the user wants an evaluation that automatically scores new
  `$ai_generation` events going forward — "create an eval to catch X", "continuously check that responses
  do Y", "turn this failure into an eval". Covers choosing the eval type (hog / llm_judge / sentiment),
  gating on the team's provider key before an llm_judge eval, scoping which events fire via
  conditions (property filters + rollout sampling), creating it disabled, verifying scope, and enabling.
  Finding and ranking the failure modes worth evaluating is its own job — use exploring-ai-failures first.
  To debug or manage evaluations that already exist, use exploring-llm-evaluations.
---

# Creating online evaluations

An **online evaluation** scores `$ai_generation` events automatically as they arrive, forever, until
disabled. A good eval comes from a real failure mode you've found in production traffic, not from a guess
or a generic metric like "hallucination" or "helpfulness". This skill starts once that failure mode is
identified and turns it into a scoped, continuously-running eval.

**First, know what you're evaluating.** Finding and ranking the failure modes worth catching is a
separate job. If the user doesn't specify what they want to evaluate, ask them. If they are still vague
about it and don't refer to a specific failure mode, run `exploring-ai-failures` to scope a use case,
find failing traces, and produce a ranked list of failure modes.

For the mechanics of _writing and iterating_ an evaluator (Hog source vs LLM-judge prompt, dry-running,
debugging a live eval), defer to `exploring-llm-evaluations`.

## Tools

| Tool                                   | Purpose                                                       |
| -------------------------------------- | ------------------------------------------------------------- |
| `posthog:llma-provider-key-list`       | Find a usable (`ok` state) provider key to pin (llm_judge)    |
| `posthog:llma-evaluation-judge-models` | List valid provider+model combos                              |
| `posthog:llma-evaluation-test-hog`     | Dry-run Hog source against recent generations before creating |
| `posthog:llma-evaluation-create`       | Create the evaluation (always `enabled: false` first)         |
| `posthog:llma-evaluation-run`          | Spot-run a draft eval against one generation                  |
| `posthog:llma-evaluation-update`       | Iterate config, then flip `enabled: true`                     |
| `posthog:execute-sql`                  | Verify a condition matches the events and volume you expect   |
| `posthog:generate-app-url`             | Build a region- and project-qualified deep link to the eval   |

The full create payload (every field, the config schemas, the exact `conditions` shape) is in
[references/evaluation-payload.md](references/evaluation-payload.md).

## Phase 1 — Pick the failure mode to evaluate

Start from a real, observed failure, not a metric you picked in advance. If you don't already have one,
run `exploring-ai-failures` to scope a use case, find failing traces, and produce a ranked list of failure
modes — then come back. With that list in hand, talk with the user to choose what to turn into an eval:

- **Most frequent, most painful first.** A handful of modes usually cover the majority of failures.
- **Pair obvious fixes with the eval, don't skip it.** If a prompt tweak would likely fix the failure, set
  up the eval anyway and suggest the fix alongside it — a rising pass rate is how you confirm the fix landed.
- **One mode per eval.** Three failure modes is three evals, not one prompt trying to catch everything.

You should end with a single, crisp, checkable criterion — "the reply must stay on the user's topic", "the
tool call must include an `order_id`". Then move to Phase 2.

## Phase 2 — Build the online eval

### 2.1 — Choose the eval type

| Use…        | When the criterion is…                                                                                                                |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `hog`       | Structural / rule-based (JSON parses, length, regex, tool-call shape). Cheap, deterministic, **no provider key needed.**              |
| `llm_judge` | Subjective / fuzzy (tone, factuality, on-topic). Costs an LLM call per run; needs AI data-processing approval + a provider key.       |
| `sentiment` | You want sentiment labels on user messages, not a pass/fail (unless very specifically asked for, usually not relevant to this skill). |

Reach for `hog` first, escalate to `llm_judge` if there is no deterministic way to check for what we want to check.

### 2.2 — Gate (llm_judge only)

Before creating an `llm_judge` eval, confirm it can actually run, or it errors on first fire. Hog and
sentiment skip this.

```json
posthog:llma-provider-key-list            // pick a key whose state == "ok"
posthog:llma-evaluation-judge-models      // { "provider": "openai" } → valid models
```

Every `llm_judge` eval runs on a provider key. Pick an `ok`-state key from `llma-provider-key-list` and set
it as `model_configuration.provider_key_id`.

If there's no `ok` key, stop and ask the user to add/validate one in the UI — the agent can't create keys.

### 2.3 — Create it disabled

Create with `enabled: false` so nothing fires until the scope is verified. Minimal `hog` example:

```json
posthog:llma-evaluation-create
{
  "name": "Output is valid JSON",
  "description": "Fails when the assistant message can't be parsed as JSON",
  "evaluation_type": "hog",
  "evaluation_config": { "source": "try { jsonParse(jsonParse(output)[1].message.content); return true; } catch { return false; }" },
  "output_type": "boolean",
  "output_config": { "allows_na": false },
  "conditions": [
    { "id": "default", "rollout_percentage": 100, "properties": [{ "key": "$ai_model", "type": "event", "operator": "icontains", "value": "gpt" }] }
  ],
  "enabled": false
}
```

For `llm_judge`, swap `evaluation_config` to `{ "prompt": "…" }` and add
`"model_configuration": { "provider": "openai", "model": "gpt-5-mini", "provider_key_id": "<uuid of an ok-state key from llma-provider-key-list>" }`.
Full field reference: [references/evaluation-payload.md](references/evaluation-payload.md).

### 2.4 — Verify the scope before enabling

`conditions` is where online evals go wrong: too broad and you evaluate (and bill) a firehose; too narrow
and it never fires. Confirm the filter matches the events you expect, and roughly how many per day:

```sql
posthog:execute-sql
SELECT count() AS matched, count() / 7 AS per_day
FROM events
WHERE event = '$ai_generation'
    AND properties.$ai_model ILIKE '%gpt%'      -- mirror each condition property
    AND timestamp >= now() - INTERVAL 7 DAY
```

If volume is high, set `rollout_percentage` below 100 to sample. Spot-check the evaluator with
`llma-evaluation-test-hog` (hog) or `llma-evaluation-run` against one generation (llm_judge).

> **Watch out:** some orgs reuse a single `$ai_trace_id` across 100k+ events. Scoping by trace-ID prefix
> can match far more than expected — verify volume with the SQL above before enabling.

### 2.5 — Enable, then close the loop

```json
posthog:llma-evaluation-update
{ "evaluationId": "<uuid>", "enabled": true }
```

It now runs on every new matching `$ai_generation`. This isn't one-and-done: the user should be aware that
they need to keep an eye on results and iterate if the outcome is not the expected one. To wire results
into a Slack feed, see `feature-usage-feed`.

## Scoping with conditions

`conditions` is a **list** of condition sets — **OR between sets, AND within a set's `properties`**. Each
set is `{ id, rollout_percentage, properties[] }`. There is no time window inside conditions; sampling is
only `rollout_percentage` (0–100). Property filters use the standard PostHog shape
(`key`, `type`, `operator`, `value`).

```json
"conditions": [
  { "id": "openai",    "rollout_percentage": 100, "properties": [{"key": "$ai_provider", "type": "event", "operator": "exact", "value": "openai"}] },
  { "id": "anthropic", "rollout_percentage": 25,  "properties": [{"key": "$ai_provider", "type": "event", "operator": "exact", "value": "anthropic"}] }
]
```

## Constructing UI links

Build links with `posthog:generate-app-url` — never hand-write the host or the `/project/<id>/` prefix.
Pass the canonical path templates:

- **Evaluations list:** `generate-app-url {url: "/ai-evals/evaluations"}`
- **Single evaluation:** `generate-app-url {url: "/ai-evals/evaluations/<evaluation_id>"}`

These resolve to the correct region host and project prefix (e.g.
`https://us.posthog.com/project/<id>/ai-evals/evaluations/<evaluation_id>`). Surface the link after
creating so the user can review and toggle it in the UI.

## Tips

- **Evals come from real failures, not generic metrics.** Start from a failure found in this product's
  traffic (via `exploring-ai-failures`), not from "let's measure hallucination". A metric nobody traced
  back to a real bad output is noise.
- **One eval, one failure mode.** Different failure modes need different evals; don't make one eval try to
  catch everything.
- **Suggest changes along with the eval if possible.** If it's clear a prompt change would fix the issue, for
  instance, set up the eval but also suggest to the user they change the prompt: they should soon see the eval
  go from low pass rate to a higher pass rate.
- **`hog` first.** No provider key, no AI approval, deterministic. Reach for `llm_judge` only when the
  criterion genuinely can't be coded.
- **Always create disabled, verify scope, then enable.** An eval firing on the wrong events is worse than
  none — noise, and (for llm_judge) cost.
- **Gate llm_judge before creating**, not after. A judge eval with no usable provider key errors on first run.
- **`bytecode` is server-written** for hog evals — never pass it; send only `evaluation_config.source`.
- For cluster-scoped evals, identify the cluster with `exploring-llm-clusters`, then translate its event
  filter into `conditions`.
