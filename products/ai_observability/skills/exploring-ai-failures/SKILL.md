---
name: exploring-ai-failures
description: >
  Find where an AI/LLM application is failing in production and surface the failure patterns, working from
  real traces. Use when someone wants to understand what's going wrong with an AI feature, find and
  categorize failure modes, triage errors, or investigate quality issues (wrong answers, ignored
  instructions, hallucinations, tool misuse) — "what's failing in my agent", "surface error patterns",
  "why are the responses bad", "find the common failure modes", "what should I fix next". Covers scoping
  to one use case, finding failing traces by whichever signal fits the context (code errors, metric
  outliers, trace-type slices, manual review, existing-eval spikes, clustering), and reading them into a
  ranked failure taxonomy.
---

# Exploring AI failures

The highest-value thing you can do with production AI traffic is look at where it fails and name the
patterns. The catch: **most failures are silent.** The model returns a clean response — HTTP 200, no
exception — that is wrong, off-topic, ignores an instruction, or misuses a tool. Those never raise an
error, and they're usually the failures worth caring about.

So this skill is about finding failures (loud _and_ silent), **reading them**, and grouping them into a
**ranked set of failure modes** you can act on: fix a prompt, file a bug, prioritize work, or turn the
top mode into an automatic eval (`creating-online-evaluations`).

**Everything below serves one irreducible activity: reading real traces.** The queries only tell you
_which_ traces to open — they are never the answer. If you report a list of problems without having
opened traces, you've described the loud minority (the things that throw errors) and missed the job.

This is bottom-up: the failure modes emerge from real traces, not from a list of generic metrics decided
in advance. For reading a single trace in depth, lean on `exploring-llm-traces`; for emergent grouping at
high volume, `exploring-llm-clusters`.

## Tools

| Tool                                     | Purpose                                                                  |
| ---------------------------------------- | ------------------------------------------------------------------------ |
| `posthog:query-llm-traces-list`          | List candidate traces — filter by error, sort by a metric, scope by type |
| `posthog:query-llm-trace`                | Read a trace in full to see what actually went wrong                     |
| `posthog:execute-sql`                    | Find metric outliers, discover the trace taxonomy, count failure modes   |
| `posthog:llma-evaluation-list`           | Find existing evals whose failures might reveal a new mode               |
| `posthog:llma-evaluation-summary-create` | Summarize an existing eval's failures into patterns                      |
| `posthog:generate-app-url`               | Build a region- and project-qualified deep link to a trace or list       |

Detailed queries for each strategy below are in
[references/finding-traces.md](references/finding-traces.md). The full `$ai_*` event schema (and the
`events` vs `ai_events` split for heavy content like `$ai_input`/`$ai_output_choices`) lives in
`exploring-llm-traces/references/events-and-properties.md`.

## Work with the user

Collaborate on _scope and priorities_ — not on whether to do the work. Narrow with the user up front:
which feature or use case? have they already seen something bad? is there a signal to follow (a
thumbs-down, a ticket, a metric that looks off)? Once it's scoped, **go read traces and come back with
coded failure modes** — don't stop to ask permission before the reading; that reading is the core
activity, not an optional follow-up to offer. When the user doesn't know what to look for, drive the loop
below and explain the reasoning as you go; keep the teaching opt-in.

## Step 1 — Scope to one use case

Apps have a _taxonomy_ of trace types, and each fails differently — a support chat hallucinates policy, a
summarizer drops key points, an agent loops or misuses a tool. Evaluating or analyzing them together
averages the signal away. **Pick one**, then find its filter (a `$ai_trace_id` prefix, a feature
property, a model). If the user isn't sure how their traffic splits, discover the taxonomy first (query
in [references/finding-traces.md](references/finding-traces.md)).

## Step 2 — Pick which traces to read

These are ways to _select which traces to open_ — not answers in themselves. The queryable ones (error
counts, metric aggregates) tell you _where to look_; they are never the output. Choose by the context and
signals you have, and combine them:

- **Code errors (`$ai_is_error`)** — the cheapest sweep and the _least_ representative signal: it only
  catches exceptions and API failures, not the silent quality failures that matter most. Use it to grab a
  few traces to read, not as a tally of "the problems." Slightly more useful for structured-output or
  tool-calling pipelines, where some failures do surface as parse/schema errors.
- **Metric outliers** — sort by output/input tokens, message length, cost, or latency and open the
  extremes. Runaway length, truncation, context bloat, and loops cluster at the tails.
- **One trace-type slice** — narrow to a single kind of request so the traces you read share a taxonomy.
- **Stratified sample** — when you have no specific signal (the common case), pull a mixed batch across
  slices and outcomes and read it. This is the default, not the fallback.
- **Existing-eval spikes** — when evals already run, a jump in an eval's failures points you at traces to
  read (`llma-evaluation-list` + `llma-evaluation-summary-create`).
- **Clustering** — at high volume, let groupings emerge to pick representative traces to read; see
  `exploring-llm-clusters`.

> **The trap.** It's tempting to `GROUP BY` error messages, produce a ranked table, and stop. That table
> is the loud minority — failures that raise an exception. The failures that matter for most AI products
> complete with HTTP 200 and only appear when a human reads the trace. **A ranking built from error or
> metric counts you never opened is not the deliverable** — it's a pointer to what to read next. If a
> query for silent failures comes back empty or awkward, that's a signal to _read traces_, not to give up
> and report the loud ones.

## Step 3 — Read a batch (this is the job)

Open and actually read the traces you selected — plan on roughly 20–30 for a use case. This step is not
optional, and nothing substitutes for it. You **cannot** find silent failures with `GROUP BY` or by
grepping outputs for "refusal" / "sorry" language, because you don't yet know the patterns to search for —
reading is how you discover them. A clever SQL proxy that returns nothing is not evidence the failures
aren't there; it means you have to read.

For each trace, note in plain language what went wrong — and jot down the trace's earliest-event timestamp
alongside the note (it's right there in the trace you just read, and in `query-llm-traces-list`'s
`createdAt`). That timestamp and the trace ID is all you need to build a resolvable deep link in Step 4,
so capturing it now saves a second round-trip later.

When a trace fails in a chain, record the _first_ thing that broke — the root failure usually causes the
downstream symptoms, and fixing it clears them. Group the notes into a few named failure modes
("ignores the date filter", "invents a policy", "drops the second question"); a later pass can help
cluster your notes, but review the groupings yourself. Keep reading until new traces stop turning up
new modes (tens of traces, not thousands — stop when it goes quiet).

## Step 4 — Rank, link, and hand back to the user

Rank the modes you found _by reading_, roughly by how often they showed up in your sample — a handful
usually dominate. Present a short, ranked list of named failure modes. For each mode, include **one or two
example trace deep links** on your own — don't wait to be asked, and don't make the user request them.

You read these traces, but you can misread one — a trace that looks like a hallucination may be correct in
context, and some of what you flag will be you misunderstanding the trace, not a real failure. So don't
present the list as settled fact. Give the user a couple of linked examples per mode, ask them to open the
links, then ask **which mode they want to focus on** next.

(A list assembled from error messages or metric counts you never read is the loud subset, not this — go
back to Step 3.)

## When there's little to look at

If the use case is new or low-volume and you can't find enough failures: widen the time window or loosen
the slice first; then **stress-test** with inputs that deliberately probe the constraints you care about
(edge cases, long or ambiguous inputs, adversarial phrasing); or **generate a small synthetic set** across
the dimensions that matter (request type × user scenario), run it through the system, and read those
traces. Treat synthetic results as a bootstrap, not ground truth — they're unreliable for high-stakes or
niche domains.

## Constructing UI links

`query-llm-trace` does not return a `_posthogUrl`, so build links with `posthog:generate-app-url` —
never hand-write the host or the `/project/<id>/` prefix. Pass the canonical path templates:

- **Traces list:** `generate-app-url {url: "/ai-observability/traces"}` (then filter to your use case)
- **Single trace:** `generate-app-url {url: "/ai-observability/traces/<trace_id>"}`, then append
  `?timestamp=<url_encoded_timestamp>` to the returned URL (the timestamp isn't expressible via the tool).

These resolve to the correct region host and project prefix (e.g.
`https://us.posthog.com/project/<id>/ai-observability/traces/<trace_id>`), so a user not already on the
target project still lands in the right place.

## Tips

- **Reading is the job, not the last step.** Aggregates, error counts, and scores are clues for _which
  traces to open_ — never a substitute. Read a first batch before reporting anything, and don't ask
  permission to do it.
- **Don't over-index on errors.** `$ai_is_error` is the loudest but least interesting signal; the
  failures worth your time usually complete without one.
- **The finding strategies are a menu for picking traces to read**, not a pipeline and not the answer.
  Pick by context, combine freely, and don't force an order.
- **One use case at a time.** Different trace types have different failure taxonomies — mixing them blurs
  the result.
- **Frequency over completeness.** The goal is the modes that happen most, not every conceivable failure.
- **The output is a ranked list of named failure modes from traces you read** — that artifact is what
  makes the next step (fix, prioritize, or eval) obvious.
- **Hand back linked examples, then let the user steer.** Don't stop at a categorical table. Give one or
  two resolvable trace links per mode unprompted, ask the user to eyeball a couple.
