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
- Layout: by default preserve existing tile placement. Only reflow (`dashboard-reorder-tiles`) when the user explicitly
  asks to rearrange, reorder, or move tiles.
- Verify with `dashboard-insights-run` to confirm the tiles return data, then summarize what you built and invite the
  user to refine it.

## When not to use this

- Saving a single insight — just create the insight; it doesn't need a dashboard.
- Adding non-insight widget tiles (text cards, widgets) — see the widget tools (`dashboard-widget-catalog-list`,
  `dashboard-widgets-batch-add`) instead.
