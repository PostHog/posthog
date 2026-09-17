---
name: building-a-dashboard
description: >
  Build a new dashboard, or update an existing one, from a set of insights — the same job the in-app
  assistant does with its upsert-dashboard tool, but over MCP. Use when a user asks to create a dashboard,
  put several metrics/charts together on one page, assemble a dashboard for a topic (product analytics,
  retention, revenue, activation, etc.), or add/remove/replace insights on a dashboard they already have.
  Covers deciding create vs update, reusing existing insights vs creating new ones, and using PostHog's
  vetted dashboard templates as reference for what a strong dashboard on a topic looks like.
---

# Building a dashboard

A dashboard is a collection of insight tiles on one page. Your job is to figure out which insights belong on it,
reuse what already exists, create what's missing, and lay them out sensibly — not to blindly generate charts.

## Create vs update

First work out whether you're creating a new dashboard or changing an existing one.

- Search existing dashboards with `dashboards-get-all` (its `search` param does fuzzy name/description matching). If the
  user is clearly describing something that already exists, they probably want an update.
- Read a candidate with `dashboard-get` to see its current tiles before you change anything.
- If the request is ambiguous — "get my financial metrics together" could mean build new or add to an existing one —
  ask a short clarifying question rather than guessing.

## Use templates as reference

PostHog ships vetted dashboard templates for common topics, and orgs can share their own. Consult them before you
build — they're a strong signal of which insights pair well on a topic.

1. `dashboard-templates-list` — browse templates (use `search` for a topic, `scope` to narrow to global / team /
   organization). This returns names, descriptions, and tags only.
2. `dashboard-templates-retrieve` — open the closest template to see its `tiles`: which insights it groups together and
   how each is queried.

Treat templates as **examples, not a spec**. Take inspiration from the insights and their groupings, but tailor every
insight to the user's own events, properties, and intent. Don't copy a template verbatim, and don't force a template
onto a request it doesn't fit — a good bespoke dashboard beats a mismatched template every time.

## Select the insights

Prefer reusing existing insights over recreating them.

- Search with `insights-list` and read promising ones with `insight-get` to check they match the user's intent and
  actually have data. Full-text search misses things named differently, so list broadly before concluding an insight
  doesn't exist.
- For anything missing, create it with `insight-create` (see the product-analytics insight skills for query shape).
- Keep the set minimal — only the insights the request needs. A focused dashboard is more useful than an exhaustive one.

## Assemble the dashboard

- New dashboard: `dashboard-create` with a short (3–7 word) name and a concise description, then add the insight tiles.
- Existing dashboard: `dashboard-update`. Adding, replacing, or removing insights means sending the full intended set of
  tiles — insights you omit are removed, so include the ones you want to keep.
- Layout: by default preserve existing tile placement. Use `dashboard-update` to plan each tile independently on the
  12-column grid. Tile widths can be any whole number from 1 to 12, subject to each tile's minimum size. Use wider
  tiles for primary charts and smaller tiles for supporting metrics. Mixed rows such as 8 plus 4 or 6 plus 6 can show
  that hierarchy.
- Reflow: use `dashboard-reorder-tiles` only when the user explicitly asks to reorder tiles or make every tile the
  same size. Its layout modes give every tile a uniform box. For mixed widths or heights, use `dashboard-update`.
- Tile sizes: send `tiles` through `dashboard-update` with each tile's `id` and one or both layout boxes. A layout update
  changes only the submitted breakpoint. For example, `layouts.xs` preserves the stored `layouts.sm` box. Send a complete
  `layouts.sm` box when a tile has no desktop placement. The API stores only `x`, `y`, `w`, and `h`. It does not resolve
  overlaps, so plan the grid before you send it.
- Verify with `dashboard-insights-run` to confirm the tiles return data, then summarize what you built and invite the
  user to refine it.

## When not to use this

- Saving a single insight — just create the insight; it doesn't need a dashboard.
- Adding non-insight widget tiles (text cards, widgets) — see the widget tools (`dashboard-widget-catalog-list`,
  `dashboard-widgets-batch-add`) instead.

## Related skills

- **`managing-subscriptions`** — deliver the finished dashboard to email or Slack on a schedule
- **`creating-ai-subscription`** — a recurring AI-written report, when prose beats a wall of charts
