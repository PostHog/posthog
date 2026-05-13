---
name: find-the-money
description: >
  Audits a PostHog project to surface ranked, qualitative revenue opportunities —
  whale concentration, free-to-paid lookalikes, upsell candidates inside paid tiers,
  channel ROI, dormant payers, conversion leaks, and time-to-value gaps. Read-only;
  produces a single `find-the-money-{date}.md` report with evidence, recommendations,
  implementation checklists, and the HogQL it ran in an appendix. Use when the user
  asks "where is the money?", "find revenue opportunities", "where can we grow
  revenue?", "how do I increase revenue?", wants upsell or expansion ideas, wants to
  identify high-value segments, spot at-risk revenue, or asks to run a revenue audit.
  Triggered by a guided wizard that gathers business shape (subscription / one-time /
  usage / mixed), focus area (grow / expand / save / surprise me), data hints, and
  exclusions before the skill runs.
---

# Find the money

A read-only revenue audit. The skill reads PostHog events, persons, groups, and
warehouse tables to surface ranked opportunities and writes a single markdown report
to `./find-the-money-{date}.md`. It never creates cohorts, insights, dashboards, or
annotations — every recommendation is a checklist item the user implements themselves.

## When to use this skill

The user wants to find revenue upside in their existing data — they don't have a
specific metric anomaly to investigate (use `investigate-metric` for that), and they
don't yet know which segment, channel, or feature to focus on. The skill's job is to
do the looking and rank what it finds by confidence.

If the project has no revenue signal at all (no `$revenue` property, no warehouse
billing source, no plan property), the skill outputs an "instrument this first"
report instead of failing — that's still a useful answer.

## Tools

| Tool                                 | Purpose                                             |
| ------------------------------------ | --------------------------------------------------- |
| `posthog:read-data-schema`           | Detect revenue events, plan properties, group types |
| `posthog:read-data-warehouse-schema` | Detect Stripe / billing tables                      |
| `posthog:external-data-sources-list` | Confirm which warehouse sources are connected       |
| `posthog:execute-sql`                | HogQL for every analysis                            |
| `posthog:query-trends`               | Revenue / activity over time (for context only)     |
| `posthog:query-funnel`               | Confirming a conversion-leak hypothesis             |
| `posthog:feature-flag-get-all`       | Identifying features behind paywalls / experiments  |

## Workflow

### Step 1 — Wizard intake

A guided wizard collects inputs before invoking the skill. If invoked outside the
wizard, ask the same questions in order — do not guess.

See [wizard-questions.md](./references/wizard-questions.md) for the full question set
with branching. The minimum required to proceed:

- **Business shape** — subscription / one-time / usage-based / ads / mixed
- **Buyer unit** — individual person or org/team (decides person vs group analytics)
- **Focus** — grow new revenue / expand existing / save at-risk / surprise me (all three, shallower each)
- **Time window** — default 90 days
- **Exclusions** — internal emails, test orgs, employees

Three optional but high-value questions:

- Revenue event name / property (autodetect if `$revenue`, `purchase`, `subscription_created` exist)
- Plan/tier property name (autodetect `plan`, `subscription_tier`, `pricing_plan`)
- What have you already tried that didn't work? — keeps the report from recommending the same thing

### Step 2 — Discover revenue signals

Run these in parallel before any analysis:

1. `posthog:read-data-schema` — look for revenue-shaped events and `$revenue` /
   `revenue` / `amount` / `price` properties.
2. `posthog:external-data-sources-list` + `posthog:read-data-warehouse-schema` —
   look for Stripe, Chargebee, Shopify, or generic billing tables.
3. Sample query for a plan property: `SELECT DISTINCT properties.plan FROM events LIMIT 20`
   (try common names from the wizard answer).

Classify the project into one of:

- **Rich** — has both events and warehouse billing. Run the full catalog.
- **Events-only** — revenue in events only. Skip warehouse-specific analyses (LTV, MRR).
- **Warehouse-only** — billing in warehouse, no revenue events. Join warehouse tables
  to `persons` / `events` on email.
- **No signal** — output the "instrument this first" report (see report template).

### Step 3 — Run analyses

Run analyses in parallel per the wizard's focus. Each analysis is in
[query-catalog.md](./references/query-catalog.md) with the HogQL, what to look for,
and how to phrase the finding. Pick the relevant subset:

| Focus area   | Analyses                                                                 |
| ------------ | ------------------------------------------------------------------------ |
| Grow new     | conversion leak · channel ROI · time-to-value gap · pricing-page autopsy |
| Expand       | feature → upgrade correlation · tier squeeze · free-to-paid lookalikes   |
| Save at-risk | dormant payers · engagement decline · power-user churn risk              |
| Surprise me  | top 2 from each focus area (shallower depth)                             |

Cross-cutting analyses always run:

- **Whale concentration** — top decile share of revenue. Sets the baseline for every
  other finding ("affects N users = X% of revenue").
- **Segment ROI** — revenue per user by `utm_source`, country, plan, group property.

### Step 4 — Rank findings

Assign each opportunity a confidence band:

- **High** — clear statistical signal (e.g. >2× lift, n > 100) + actionable cohort
  the user can target.
- **Medium** — directional signal or smaller n, still actionable.
- **Low** — pattern matches a known opportunity shape but the data is thin; surface
  as "worth a closer look".

Sort within the report: high first, then medium, then low. Cap at ~8 opportunities
total — more than that and the report stops being actionable.

### Step 5 — Write the report

Write to `./find-the-money-{YYYY-MM-DD}.md` in the current working directory.
Format per [report-template.md](./references/report-template.md):

1. **TL;DR** — 3 bullet points naming the top 3 opportunities
2. **Opportunities** — one section per finding (ranked)
3. **Data gaps** — what couldn't be measured and why (instrumentation suggestions)
4. **Appendix** — the HogQL run for each analysis, so the user can re-run / fork

Each opportunity section contains:

- **Why this matters** — one sentence on the business mechanism
- **Evidence** — query result summary + link to a relevant PostHog page (cohort
  filters, web analytics, etc.) where possible
- **Recommended actions** — checklist of concrete steps (cohort to create, campaign
  to launch, event to instrument, pricing change to test). The skill does not
  execute these — it lists them.

Do not promise dollar estimates. Rank qualitatively (high / medium / low confidence).

## Output discipline

- **Single file** — overwrite if a same-date report already exists; warn the user.
- **No side effects** — the skill must not call any `*-create` or `*-update` MCP tool.
  All actions are deferred to the user via the report's checklists.
- **Cite the SQL** — every claim in the report references a query in the appendix by
  number (`see §A.3`). Builds trust and gives the user something to fork.
- **Acknowledge limits** — if a focus area had insufficient data, say so in
  "Data gaps" rather than padding the report with weak findings.

## Reference files

- [wizard-questions.md](./references/wizard-questions.md) — full intake question set
- [query-catalog.md](./references/query-catalog.md) — HogQL recipes per analysis
- [report-template.md](./references/report-template.md) — exact output format

## Related skills

- **`suggesting-data-imports`** — hand off when the project has no warehouse billing
  data and the user wants to connect Stripe / Chargebee / Shopify.
- **`investigate-metric`** — hand off when the user picks one opportunity from the
  report and wants to dig into a specific metric movement.
- **`querying-posthog-data`** — required reading before writing any HogQL in this
  skill's analyses.
