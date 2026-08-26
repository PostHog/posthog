---
name: creating-online-evaluations
description: >
  Author continuously-running online evaluations in PostHog AI observability, grounded in real failure
  modes you've identified. Use when the user wants evaluations that automatically score new generations
  or whole traces going forward — "create an eval to catch X", "continuously check that responses do Y",
  "turn these failures into evals". Covers letting the explored data decide how many evals to create,
  proposing that set in plain language and asking the user which ones they want, choosing the target and
  eval type (hog / llm_judge / sentiment), configuring a provider, model, and usable provider key for an
  llm_judge eval, scoping which generations trigger it via conditions, creating disabled, verifying scope,
  and enabling. Falls back to proposing a sentiment eval when no failure mode is worth catching.
  Finding and ranking the failure modes worth evaluating is its own job — use exploring-ai-failures first.
  To debug or manage evaluations that already exist, use exploring-llm-evaluations.
---

# Creating online evaluations

An **online evaluation** automatically scores either each matching `$ai_generation` or the whole trace
containing it, until disabled. A good eval comes from a real failure mode you've found in production traffic,
not from a guess or a generic metric like "hallucination" or "helpfulness". This skill starts once those
failure modes are identified and turns them into scoped, continuously-running evals.

**One eval per failure mode, and as many evals as the data justifies.** How many to create is a judgment
call you make from what the traces actually showed — sometimes one, often three or four. Never assume the
answer is one, and never bundle several modes into one evaluator.

**Propose before you create.** Bring the user a short list of candidate evals and let them pick which ones
they want (Phase 1.1). Creating evals they didn't ask for costs them money and noise.

**First, know what you're evaluating.** Finding and ranking the failure modes worth catching is a
separate job. If the user doesn't specify what they want to evaluate, ask them. If they are still vague
about it and don't refer to a specific failure mode, run `exploring-ai-failures` to scope a use case,
find failing traces, and produce a ranked list of failure modes.

For the mechanics of _writing and iterating_ an evaluator (Hog source vs LLM-judge prompt, dry-running,
debugging a live eval), defer to `exploring-llm-evaluations`.

## Tools

| Tool                                       | Purpose                                                       |
| ------------------------------------------ | ------------------------------------------------------------- |
| `posthog:llma-evaluation-config-get`       | Check the active provider key used by unpinned judges         |
| `posthog:llma-provider-key-list`           | Find a usable (`ok` state) provider key to pin                |
| `posthog:llma-evaluation-judge-models`     | List valid provider+model combos                              |
| `posthog:llma-evaluation-directory-list`   | List directories available for organizing the evaluation      |
| `posthog:llma-evaluation-directory-create` | Create a directory when the user asks for a new one           |
| `posthog:llma-evaluation-test-hog`         | Dry-run Hog source against recent generations before creating |
| `posthog:llma-evaluation-create`           | Create the evaluation (always `enabled: false` first)         |
| `posthog:llma-evaluation-run`              | Spot-run a draft eval against one generation                  |
| `posthog:llma-evaluation-update`           | Iterate config, then flip `enabled: true`                     |
| `posthog:execute-sql`                      | Verify a condition matches the events and volume you expect   |
| `posthog:generate-app-url`                 | Build a region- and project-qualified deep link to the eval   |

The full create payload (every field, the config schemas, the exact `conditions` shape) is in
[references/evaluation-payload.md](references/evaluation-payload.md).

## Phase 1 — Decide what to propose, then let the user choose

Start from real, observed failures, not metrics you picked in advance. If you don't already have them,
run `exploring-ai-failures` to scope a use case, find failing traces, and produce a ranked list of failure
modes — then come back.

### 1.1 — Turn the failure modes into a candidate set

**Let the data decide how many.** One failure mode is one eval, so a ranked list of four distinct modes is
a candidate set of four evals. Don't collapse them into one evaluator that tries to catch everything, and
don't stop at the top mode when the traces clearly showed more worth watching. Keep a candidate when:

- **It hurts.** Frequent or painful. A handful of modes usually covers the majority of failures.
- **It's checkable.** It reduces to one crisp criterion — "the reply must stay on the user's topic", "the
  tool call must include an `order_id`". If you can't state it in a line, it isn't ready to propose.
- **It's distinct.** Two candidates that would fail on the same generations are one eval.

Rank by how much they hurt and propose roughly the top five; mention in a line that you set weaker ones
aside rather than silently dropping them.

### 1.2 — Propose the set in plain language

**Never create evals the user hasn't picked.** Lay out the candidates and ask which ones they want.

Assume they haven't read the traces with you and don't know the eval vocabulary. Keep each one to a line or
two — a wall of text per eval means they can't compare them — but make it obvious what it watches and what
they'll see when it fails. No Hog snippets, property filters, or `hog`/`llm_judge` internals here. Number
them so they can reply "1 and 3":

> Found 3 failure patterns worth watching. Which should I set up?
>
> **1. Replies drift off topic** — checks the answer addresses what the user actually asked.
> Catches support replies that confidently answer a different question. Seen ~40×/day.
>
> **2. Order lookups missing an order ID** — checks every `lookup_order` call includes an `order_id`.
> Catches the silent tool failures that make the agent invent an order status. Seen ~15×/day.
>
> **3. Refuses questions it can answer** — checks the reply isn't a needless "I can't help with that".
> Catches users being turned away from things the docs cover. Costs an LLM call per check.

Per eval: what it checks, what bad thing it surfaces, and rough volume when you know it (Phase 2.5 verifies
it properly). Flag the ones needing an LLM judge, since those cost per run — that's the only mechanic worth
exposing up front. Keep the ranking implicit in the order; skip scoring tables.

Recommend a starting point if they seem unsure (usually the top one or two), and treat "all of them" or "go
ahead" as accepting the whole set. If a prompt tweak would likely fix a mode, suggest the fix alongside the
eval rather than in place of it — a rising pass rate is how they confirm the fix landed.

### 1.3 — When nothing surfaced, propose sentiment

If the traces were read and no failure mode is worth an eval, don't invent a failure and don't come back
empty-handed. Say what you looked at, then propose a `sentiment` eval as the floor:

> No clear failure pattern in the last 7 days. Worth starting with:
>
> **1. User frustration** — labels each user message positive, neutral, or negative.
> Shows which conversations are going badly, which is usually where the real failures hide. No judge cost.

It needs no provider key, it's cheap, and it gives them a signal to come back to once there's enough traffic
to spot patterns.

**No generations means no eval of any kind.** Sentiment only scores matching `$ai_generation` events, so if
the project has none, every eval you could create — sentiment included — would sit there never firing. Don't
propose one. Point them at `instrument-llm-analytics` to get AI observability capturing generations first,
and come back to this skill once there's traffic to read.

## Phase 2 — Build each accepted eval

Run 2.1 through 2.5 once per eval the user picked, so each one lands as a verified draft. **Leave every one
of them disabled until the whole set is verified** — 2.6 is a single pass over the finished set at the end,
not the last step of each loop. Enabling eval 1 while eval 3 is still being written puts a partially live
set into production, which is noise and (for a judge) cost the user didn't agree to yet.

### 2.1 — Choose the eval type

| Use…        | When the criterion is…                                                                                                                |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `hog`       | Structural / rule-based (JSON parses, length, regex, tool-call shape). Cheap, deterministic, **no provider key needed.**              |
| `llm_judge` | Subjective / fuzzy (tone, factuality, on-topic). Costs an LLM call per run; needs a provider, model, and usable provider key.         |
| `sentiment` | You want sentiment labels on user messages, not a pass/fail (unless very specifically asked for, usually not relevant to this skill). |

Reach for `hog` first, escalate to `llm_judge` if there is no deterministic way to check for what we want to check.

### 2.2 — Choose the target

| Target       | Behavior                                                                                                           |
| ------------ | ------------------------------------------------------------------------------------------------------------------ |
| `generation` | Runs once for each matching `$ai_generation`, immediately after ingestion. This is the default.                    |
| `trace`      | Runs once for the whole trace after the first matching generation and a configurable wait for the trace to finish. |
| `session`    | Runs once for the whole `$ai_session_id` session, after the session settles.                                       |

For a trace target, send `"target": "trace"` plus a settle config that controls when the trace is
evaluated, discriminated on `strategy`:

- `{ "strategy": "fixed_window", "window_seconds": 1800 }` — evaluate a fixed wait after the first
  matching generation. Between 10 seconds and 2 hours, defaults to 30 minutes. A `target_config`
  without a `strategy` key means this.
- `{ "strategy": "inactivity", "quiet_period_seconds": 300, "max_age_seconds": 7200 }` — evaluate once
  the trace has had no new activity for the quiet period (10 seconds to 30 minutes,
  defaults to 5 minutes). `max_age_seconds` caps the total wait from the first matching generation
  (1 minute to 2 hours, defaults to 2 hours, must be at least the quiet period).

A `session` target takes the same settle config with session-sized bounds, and defaults to
`inactivity` rather than `fixed_window`:

- `{ "strategy": "inactivity", "quiet_period_seconds": 3600, "max_age_seconds": 86400 }` — evaluate
  once the session has had no new activity for the quiet period (10 seconds to 24 hours, defaults
  to 1 hour). `max_age_seconds` caps the total wait from the first matching generation (1 minute to
  7 days, defaults to 24 hours, must be at least the quiet period).
- `{ "strategy": "fixed_window", "window_seconds": 1800 }` — evaluate a fixed wait after the first
  matching generation (10 seconds to 7 days).

A session evaluation only fires for events that carry `$ai_session_id`. Producers either set it on
every generation or on none, so an SDK that does not set it will never trigger a session
evaluation. `$ai_session_id` is not `$session_id`: the second is PostHog's product-analytics
session and is unrelated.

A session evaluation can also come back skipped rather than graded. The emitted `$ai_evaluation`
event then carries `$ai_evaluation_skipped: true` and an `$ai_evaluation_skip_reason`, and its
`$ai_evaluation_result` is `false` when the evaluation disallows N/A, so any analysis of pass rates
has to exclude skipped runs rather than count them as failures. Sessions are skipped when
they hold more than 2500 events (usually a session id shared across conversations), when nothing
was found in the evaluation window, and, for an LLM judge, when the transcript is too long to send
in full.

A session is evaluated at most once per evaluation, for as long as the completed run stays inside
Temporal's retention window. A session that resumes long after being evaluated may be evaluated
again, so pick a quiet period long enough that the session is really finished. A longer quiet period
costs only latency.

Conditions still match the generation that triggers the run; the evaluator itself receives
the complete trace or session. Sentiment evaluations support only the generation target.

New Hog source should use the globals shared by all targets:

| Global                                 | Meaning                                                                                              |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `evaluation_events`                    | One generation event for a generation target, or every captured event for a trace or session target. |
| `target`                               | The target's `type`, `id`, `total_cost_usd`, and `total_latency_seconds`.                            |
| `item.input_text` / `item.output_text` | Best-effort readable projections; use these for length, keyword, and regex checks.                   |
| `item.input` / `item.output`           | Original serialized values; use these when the evaluator needs to parse the captured JSON itself.    |

For a session target, `target.id` is the session id, and `target.total_cost_usd` /
`target.total_latency_seconds` are summed across the session's traces. `total_latency_seconds` is time
spent on AI work, not session wall-clock; the two can differ by orders of magnitude. Session wall-clock
is derivable from `evaluation_events` timestamps.

Generation evaluations still expose top-level `input`, `output`, `properties`, and `event`. Trace evaluations
still expose their original `events` and `trace` globals. Those globals are kept for compatibility with saved
evaluators. Session evaluations do not carry them: session Hog source only receives `target` and
`evaluation_events`. Do not use target-specific globals in new source that needs to work across targets. The
text projections recognize common provider payloads but are not authoritative; use `item.input` / `item.output`
when exact structure matters.

### 2.3 — Configure the LLM judge

An `llm_judge` evaluation requires a valid `provider` and `model`. It also needs a usable provider key
when it runs. `provider_key_id` controls whether the evaluation pins one specific key:

- Set `provider_key_id` to the UUID of an `ok`-state key for the same provider to pin it.
- Set `provider_key_id` to `null` to use the team's active provider key. The active key must be in the
  `ok` state and use the same provider as `model_configuration.provider`.

Hog and sentiment evaluations skip this step.

```json
posthog:llma-evaluation-config-get        // check active_provider_key for an unpinned judge
posthog:llma-provider-key-list            // find an ok-state key to pin
posthog:llma-evaluation-judge-models      // {} → every provider and its models; { "provider": "openai" } narrows it
```

Confirm the provider and model with `llma-evaluation-judge-models`.
Call it with no arguments to see the whole catalog at once.
Providers PostHog funds no models for come back empty unless you pass `key_id` for one of the team's keys; the response's `providers` list flags which ones those are.
Prefer pinning the chosen key so a later team-wide active-key change does not change how the evaluation runs.
Leave `provider_key_id` as `null` only after `llma-evaluation-config-get` confirms the active key is usable and its provider matches.

If there is no usable key, you may still create a disabled draft for the user to review. Do not spot-run or
enable it. Ask the user to add or validate a key in the UI before continuing.

### 2.4 — Create it disabled

Create with `enabled: false` so nothing fires until the scope is verified. Minimal `hog` example:

Evaluations may be created at the top level or in one directory. If the user names a directory, call
`posthog:llma-evaluation-directory-list` and pass its UUID as `directory_id`. Create a directory only when
the user asks for one. Omit `directory_id` or pass `null` for the top level. Directories cannot be nested.

```json
posthog:llma-evaluation-create
{
  "name": "Output is not empty",
  "description": "Fails when a generation has no readable output",
  "evaluation_type": "hog",
  "evaluation_config": { "source": "let count := 0\nfor (let i, item in evaluation_events) {\n    if (item.event == '$ai_generation') {\n        count := count + 1\n        if (length(trim(item.output_text)) == 0) { return false }\n    }\n}\nreturn count > 0" },
  "output_type": "boolean",
  "output_config": { "allows_na": false },
  "target": "generation",
  "target_config": {},
  "conditions": [
    { "id": "default", "rollout_percentage": 100, "properties": [{ "key": "$ai_model", "type": "event", "operator": "icontains", "value": "gpt" }] }
  ],
  "enabled": false
}
```

For `llm_judge`, swap `evaluation_config` to `{ "prompt": "…" }` and add
`"model_configuration": { "provider": "openai", "model": "gpt-5-mini", "provider_key_id": "<uuid of an ok-state key from llma-provider-key-list>" }`.
Use `null` only when the active team key is `ok` and uses the same provider. Full field reference:
[references/evaluation-payload.md](references/evaluation-payload.md).

### 2.5 — Verify the scope before enabling

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

For generation targets, `count()` is the run volume. For trace targets, count distinct non-empty
`$ai_trace_id` values because matching generations from the same trace schedule only one run.

If volume is high, set `rollout_percentage` below 100 to sample. Spot-check the evaluator with
`llma-evaluation-test-hog` (hog) or `llma-evaluation-run` against one generation (llm_judge).
Both tools currently use generation samples; for a trace target they can check shared source or prompt behavior,
but they do not reproduce the complete settled trace. Review the first live trace results before increasing rollout.

> **Watch out:** some orgs reuse a single `$ai_trace_id` across 100k+ events. Scoping by trace-ID prefix
> can match far more than expected — verify volume with the SQL above before enabling.

### 2.6 — Enable the verified set, then close the loop

Only once every accepted eval is a scope-verified draft, enable them — one call each:

```json
posthog:llma-evaluation-update
{ "evaluationId": "<uuid>", "enabled": true }
```

Each now runs on every new matching generation, or once per matching trace for a trace target. This isn't
one-and-done: the user should be aware that they need to keep an eye on results and iterate if the outcome
is not the expected one. To wire results into a Slack feed, see `feature-usage-feed`.

Close the loop across the whole set at once — one short list of what's now live with a link each, not a
play-by-play per eval. Mention any candidate you left disabled (no usable provider key, volume too high to
enable yet) and what would unblock it.

## Scoping with conditions

`conditions` is a **list** of condition sets — **OR between sets, AND within a set's `properties`**. Each
set is `{ id, rollout_percentage, properties[] }`. There is no time window inside conditions; sampling is
only `rollout_percentage` (0–100). Property filters use the standard PostHog shape
(`key`, `type`, `operator`, `value`). For trace targets, these filters still select the generation that
triggers the eventual whole-trace evaluation.

```json
"conditions": [
  { "id": "openai",    "rollout_percentage": 100, "properties": [{"key": "$ai_provider", "type": "event", "operator": "exact", "value": "openai"}] },
  { "id": "anthropic", "rollout_percentage": 25,  "properties": [{"key": "$ai_provider", "type": "event", "operator": "exact", "value": "anthropic"}] }
]
```

## Constructing UI links

Build links with `posthog:generate-app-url` — never hand-write the host or the `/project/<id>/` prefix.
The `url` must be a canonical catalog template; pass concrete ids via `params`, never inline them into the path.

- **Evaluations list:** `generate-app-url {url: "/ai-evals/evaluations"}`
- **Single evaluation:** `generate-app-url {url: "/ai-evals/evaluations/{id}", params: {id: "<evaluation_id>"}}`

These resolve to the correct region host and project prefix (e.g.
`https://us.posthog.com/project/<id>/ai-evals/evaluations/<evaluation_id>`). Surface the link after
creating so the user can review and toggle it in the UI.

## Tips

- **Evals come from real failures, not generic metrics.** Start from a failure found in this product's
  traffic (via `exploring-ai-failures`), not from "let's measure hallucination". A metric nobody traced
  back to a real bad output is noise.
- **One eval, one failure mode — and as many evals as the data justifies.** Different failure modes need
  different evals; don't make one eval try to catch everything, and don't default to creating exactly one
  when the traces showed several modes worth watching.
- **Propose, then create what they picked.** Show the candidate set in plain language, a line or two each,
  and wait for the user to choose. Long per-eval write-ups get skimmed, not read.
- **Nothing found still has an answer.** Traces read but no failure mode worth an eval means proposing a
  `sentiment` eval, not returning empty-handed. No `$ai_generation` events at all is the exception — no eval
  can fire, so send them to `instrument-llm-analytics` instead.
- **Suggest changes along with the eval if possible.** If it's clear a prompt change would fix the issue, for
  instance, set up the eval but also suggest to the user they change the prompt: they should soon see the eval
  go from low pass rate to a higher pass rate.
- **`hog` first.** No provider key, no AI approval, deterministic. Reach for `llm_judge` only when the
  criterion genuinely can't be coded.
- **Always create disabled, verify scope, then enable.** An eval firing on the wrong events is worse than
  none — noise, and (for llm_judge) cost.
- **Configure llm_judge credentials before running.** A judge needs a valid provider and model plus a usable
  provider key. `provider_key_id` may be `null` only when the matching active team key can be used.
- **`bytecode` is server-written** for hog evals — never pass it; send only `evaluation_config.source`.
- For cluster-scoped evals, identify the cluster with `exploring-llm-clusters`, then translate its event
  filter into `conditions`.

## Related skills

- **`exploring-ai-failures`** — find and rank the failure modes worth evaluating — do this first
- **`exploring-llm-evaluations`** — debug and manage evaluations that already exist
- **`exploring-llm-clusters`** — identify a cluster to scope cluster-targeted eval conditions
