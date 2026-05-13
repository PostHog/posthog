---
name: roast-my-funnel
description: >
  Diagnoses a specific PostHog funnel insight by identifying the worst-performing
  step, ranking likely causes, and recommending concrete fixes. Output voice is
  matched to a user-selected roast level (gentle / honest / merciless), but the
  diagnosis is factually honest regardless of tone. Read-only; prints the headline
  roast inline in chat for impact, then writes the full audit to
  `./roast-my-funnel-{date}.md` with evidence, ranked hypotheses, fix checklist,
  and HogQL appendix. Optionally suggests A/B tests for the top fix. Use when the
  user asks "roast my funnel", "why is my funnel bad?", "what's wrong with this
  funnel?", "where am I losing users?", "fix my conversion funnel", or wants a
  candid review of a specific funnel. Triggered by a guided wizard that collects
  funnel URL or short_id, time window, roast level, off-limits topics, comparison
  mode, and whether to include experiment suggestions.
---

# Roast my funnel

A read-only funnel audit with attitude. The user points at a specific funnel; the
skill finds the worst step, ranks likely causes, and recommends fixes — then
delivers the headline inline in chat in their chosen tone, and writes the full
audit to `./roast-my-funnel-{date}.md`.

The roast tone is the entertainment; the diagnosis is the value. Never compromise
diagnostic honesty for tone. Never compromise tone-of-voice rules for diagnostic
detail. See [roast-voice.md](./references/roast-voice.md) for the hard rules.

## When to use this skill

The user has a specific funnel in mind and wants a candid review of it. Not for:

- "Why did my conversion rate drop yesterday?" → use `investigate-metric`
- "Find revenue opportunities across my project" → use `find-the-money`
- "I don't have a funnel yet, help me build one" → out of scope; this skill audits,
  it does not author

If the user doesn't have a funnel URL or `short_id`, ask for one. Do not invent or
auto-pick a funnel.

## Tools

| Tool                          | Purpose                                                |
| ----------------------------- | ------------------------------------------------------ |
| `posthog:insight-get`         | Load the funnel definition (steps, filters, dateRange) |
| `posthog:insight-query`       | Run the funnel as defined                              |
| `posthog:query-funnel`        | Run variants (different window, breakdown, audience)   |
| `posthog:query-trends`        | Time-to-step trends, dropper volume over time          |
| `posthog:query-paths`         | Where droppers went after the worst step               |
| `posthog:query-trends-actors` | Sample droppers for a step (selection effects)         |
| `posthog:execute-sql`         | Anything the typed tools can't express                 |
| `posthog:read-data-schema`    | Confirm revenue signal exists (for value-weighting)    |

## Workflow

### Step 1 — Wizard intake

A guided wizard collects inputs. If invoked outside the wizard, ask the same
questions in order. See [wizard-questions.md](./references/wizard-questions.md)
for the full set. The non-skippable ones:

- **Funnel** — URL or `short_id`. Required.
- **Time window** — default 30 days.
- **Roast level** — gentle / honest / merciless. Tone only, content unchanged.

Optional but valuable:

- **Off-limits** — "I already know my landing page is bad, skip it"
- **Comparison** — prior period / sibling funnels / none
- **A/B test suggestions** — include experiment recommendations for the top fix?

### Step 2 — Load the funnel

`posthog:insight-get` with the short_id. Pull `query.kind` (must be `FunnelsQuery`
— if not, stop and explain), step definitions, current `dateRange`, audience
filters, breakdown.

If `dateRange` doesn't match the wizard's time window, override with the wizard
value when running queries — do not modify the saved insight.

### Step 3 — Run analyses in parallel

See [analysis-catalog.md](./references/analysis-catalog.md) for the queries.
Always run:

1. **Step-by-step drop** — absolute drop and relative conversion per step
2. **Time-to-next-step** — median seconds between each pair of steps (slow = intent decay)
3. **Path-after-drop** — top events / pages users hit after dropping at the worst step
4. **Dropper segments** — break the worst step by device, browser, utm_source, geo, plan; isolate selection effects

Run conditionally:

5. **Revenue-weighted drop** — only if `$revenue` / `revenue` signal exists. Re-rank steps by lost revenue, not just lost users.
6. **Sibling funnels** — only if the project has other funnel insights. Is this funnel uniquely bad, or are all funnels in the project this shape?
7. **Prior period** — only if wizard requested. Compare current period to prior.

Skip anything in the off-limits list.

### Step 4 — Synthesize findings

Pick **one** worst step. Tie-breakers: higher absolute drop > higher relative drop > higher revenue-weighted drop > later in the funnel (later drops are more expensive).

Rank hypotheses for _why_ that step underperforms (highest first):

- **Selection effect** — droppers are concentrated in a segment that shouldn't be in the funnel at all (mobile users on a desktop-only flow, bots, employee accounts). Fix: filter the audience, not the page.
- **Speed / friction** — long time-to-next-step + visible drop-off. Fix: cut steps, reduce form fields, defer optional inputs.
- **Wrong page after drop** — path-after-drop shows users going somewhere unexpected (help center, pricing, support). Fix: address the reason they bailed (confusion, sticker shock, missing info).
- **Tracking issue** — drop is too clean / too consistent / too big to be real behavior. Fix: instrumentation, not UX.
- **Comparable peers are fine** — sibling funnel comparison shows this funnel is uniquely bad. Fix: this funnel specifically, not a project-wide pattern.

Each hypothesis must be grounded in a specific query result. No vibes-based theorizing.

### Step 5 — Print the roast inline (chat)

Print the **headline roast block** (one zinger + the crime + the top fix) directly
in the chat reply. This is the moment-of-impact — keep it short. See
[report-template.md](./references/report-template.md) for the exact format. Tone
matches the user's roast level per [roast-voice.md](./references/roast-voice.md).

### Step 6 — Write the full report

Write the complete audit to `./roast-my-funnel-{YYYY-MM-DD}.md` in the current
working directory. Format per [report-template.md](./references/report-template.md):

1. Headline roast (same as chat)
2. The crime — worst step, numbers, why it qualifies
3. Why it's happening — ranked hypotheses with evidence
4. Fixes — concrete checklist; if the wizard asked for A/B test suggestions, include them per fix
5. Honorable mentions — other weak steps (no zingers, just facts)
6. What you got right — at least one positive observation
7. Data gaps — what couldn't be measured
8. Appendix — every HogQL run, numbered for citation from §3

If a same-date file already exists, overwrite and tell the user.

## Output discipline

- **No side effects.** Never call any `*-create` or `*-update` tool. Every
  recommendation is a checklist item, not an action.
- **One worst step.** Don't hedge with "could be step 2 or step 4" — pick one and
  commit. Honorable mentions cover the rest.
- **Roast voice is bounded.** Punch at the funnel, never at the user. See the hard
  rules in [roast-voice.md](./references/roast-voice.md).
- **Cite the SQL.** Every claim references a query in the appendix (`see §A.3`).
- **Acknowledge limits.** If revenue signal is missing, say so in "Data gaps" —
  don't fake a value-weighted ranking.

## Reference files

- [wizard-questions.md](./references/wizard-questions.md) — intake question set
- [analysis-catalog.md](./references/analysis-catalog.md) — HogQL recipes per analysis
- [roast-voice.md](./references/roast-voice.md) — tone rules per roast level
- [report-template.md](./references/report-template.md) — chat preview + .md format

## Related skills

- **`investigate-metric`** — hand off when the user wants to dig into _why a
  specific metric changed_ on the funnel (anomaly investigation), not what's wrong
  with the funnel itself.
- **`find-the-money`** — hand off when the user is asking about revenue
  opportunities across the project rather than a specific funnel.
- **`querying-posthog-data`** — required reading before writing any HogQL in this
  skill's analyses.
