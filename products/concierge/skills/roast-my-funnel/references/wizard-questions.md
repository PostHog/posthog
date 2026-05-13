# Wizard questions

The wizard asks these questions before invoking the skill. If you're invoking the
skill manually, ask them in the same order. Do not invent answers — when in doubt,
ask.

## Required

### 1. Which funnel?

> Paste the funnel URL or short_id.

Accept either:

- A full URL: `https://us.posthog.com/insights/aBcD1234`
- A short_id alone: `aBcD1234`
- A funnel name to look up (best effort via insight search — confirm before running)

Hard requirement: the insight's `query.kind` must be `FunnelsQuery`. If the user
points at a trends / retention / paths insight, explain why this skill can't help
and offer to redirect to the right skill (`investigate-metric` for anomalies,
`querying-posthog-data` for SQL).

If the user has no funnel in mind, **don't auto-pick one**. Ask them to point at
one or create one first.

### 2. Time window

> How far back should we look?

Default 30 days. Override the saved insight's `dateRange` for queries — do not
modify the insight itself.

### 3. Roast level

> How brutal should the roast be?

- **Gentle** — encouraging, soft phrasing, focus on the upside of the fix
- **Honest** — direct, no padding, neutral voice
- **Merciless** — comedy-roast voice, theatrical zingers

**Critical:** roast level affects voice only. The diagnosis, evidence, hypothesis
ranking, and fixes are identical across all three levels. See
[roast-voice.md](./roast-voice.md) for what each level sounds like in practice.

## Optional but high-value

### 4. Off-limits topics

> Anything you already know is bad and don't want roasted?

Use cases:

- "Landing page is bad, I'm rebuilding it next quarter" → exclude landing page steps from the worst-step pick
- "Mobile experience is broken, skip mobile-specific findings" → filter out mobile-only segments
- "Don't suggest copy changes, we just hired a copywriter" → skip copy-related fixes

The skill should respect off-limits in the _worst step pick_, not just in the
write-up. If the worst step is off-limits, pick the next-worst and note the
exclusion in "Data gaps."

### 5. Comparison mode

> Compare this funnel to anything?

- **Prior period** — same funnel, prior {time_window}. Reveals whether the funnel
  was always this bad or got worse.
- **Sibling funnels** — other funnels in the same project. Reveals whether the
  funnel is uniquely bad or all funnels in the project share the pattern.
- **None** — skip comparison analyses (faster, less context).

Default: none. Comparisons add useful context but double the query time.

### 6. A/B test suggestions

> Want the report to suggest A/B tests for the top fix?

- **Yes** — include a "How to validate this fix" subsection per recommendation
  with a concrete experiment design (hypothesis, variants, metric, sample size
  guidance).
- **No** — fixes-only, no experiment design.

Default: no. Adds length to the report; opt-in for users who actually plan to test.

## Branching notes

- If the funnel has fewer than 3 steps, the analyses still run but "honorable
  mentions" will be thin. Note this in the report rather than hiding it.
- If the worst step's drop is below a sanity threshold (say, <5% drop), warn that
  the funnel isn't obviously broken — the user may be looking for problems that
  aren't there. Still run, but caveat the headline.
- If the funnel has 0 users entering it in the window, output an "instrument
  this first" report — no users means no diagnosis is possible.
