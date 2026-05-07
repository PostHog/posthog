# MCP Tools & Skills — Team Coverage Report

Generated 2026-05-07. Source of truth: `products/*/product.yaml` (owner field) cross-referenced with the team list at https://posthog.com/teams.

Saved insight (stacked bar of MCP tools + skills per team): [/insights/xftwxwIH](/insights/xftwxwIH).

## Methodology

- Team list pulled from https://posthog.com/teams (50 teams).
- Product ownership read from each `products/*/product.yaml` `owners:` field.
- MCP tool count = entries with `enabled: true` in `products/*/mcp/tools.yaml`.
- Skill count = `SKILL.md` files under `products/*/skills/**`.
- Engineering teams without a product directory in this monorepo (e.g. Cloud Foundations, Client Libraries, Platform UX) and non-engineering teams (sales, marketing, ops, etc.) are listed in separate sections below.

## Engineering teams that own a product directory

| Team | Products owned | MCP tools (enabled) | Skills | Status |
|---|---|---:|---:|---|
| LLM Analytics | llm_analytics | 52 | 6 | Both |
| Managed Warehouse | data_warehouse | 35 | 5 | Both |
| Experiments | experiments | 17 | 6 | Both |
| Replay | replay, desktop_recordings | 9 | 4 | Both |
| Signals | signals, tracing | 11 | 3 | Both |
| Feature Flags | feature_flags, early_access_features | 23 | 2 | Both |
| Product Analytics | product_analytics, dashboards, event_definitions | 17 | 2 | Both |
| Web Analytics | web_analytics, marketing_analytics | 2 | 1 | Both |
| PostHog AI | posthog_ai, mcp_analytics, mcp_store, slack_app | 2 | 3 | Both |
| Logs | logs | 17 | 1 | Both |
| Developer Experience | visual_review, metrics | 9 | 1 | Both |
| Error Tracking | error_tracking | 16 | 0 | MCP only |
| Platform Features | platform_features, notebooks, notifications, tasks, links | 26 | 0 | MCP only |
| Workflows | workflows, cdp, messaging | 5 | 0 | MCP only |
| Surveys | surveys | 8 | 0 | MCP only |
| Customer Analytics | customer_analytics, revenue_analytics | 6 | 0 | MCP only |
| Conversations | conversations, business_knowledge | 4 | 0 | MCP only |
| Batch Exports | batch_exports | 6 | 0 | MCP only |
| Analytics Platform | alerts, analytics_platform, query_performance_ai | 7 | 0 | MCP only |
| Data Modeling | data_modeling, endpoints | 10 | 0 | MCP only |
| Growth | growth, product_tours, user_interviews, legal_documents | 0 | 1 | Skills only |
| Warehouse Sources | warehouse_sources_queue | 0 | 0 | Neither |
| Data Tools | streamlit_apps | 0 | 0 | Neither |
| Ingestion | managed_migrations | 0 | 0 | Neither |
| ClickHouse | live_debugger | 0 | 0 | Neither |

Notes:
- "Flags Platform" appears on posthog.com/teams but no product.yaml maps to a `team-flags-platform` owner — ownership in this repo currently rolls up to `team-feature-flags`.
- The `core_events` product is owned by `team-events`, which does not appear on the public teams page; treating it as part of Ingestion / Product Analytics scope.
- `access_control` has owner `team-CHANGEME` (placeholder) — excluded from the table until ownership is set.

## Engineering teams on posthog.com/teams with no product directory in this repo

These are engineering teams whose code does not live under `products/` in this monorepo — typically infra, platform, or SDK work in separate repos or directories. Not expected to ship product-level MCP tools or skills, but listed for completeness.

- Blitzscale — special-projects engineering team
- Client Libraries — SDKs in `posthog-js`, `posthog-python`, etc.
- Cloud Foundations — cloud infrastructure
- Docs & Wizard — docs and onboarding wizard
- Flags Platform — work currently rolls up to `team-feature-flags` in this repo
- Forward Deployed Engineering — customer-facing engineering
- Onboarding — no `product.yaml` owner found
- Platform UX — frontend platform
- PostHog Code — internal agent tooling (this team)
- Security — security engineering

## Non-engineering teams on posthog.com/teams

Out of scope for this report — listed only to confirm we accounted for every team on the public page.

Billing, Customer Success, Demand Gen, Editorial, Graphics, IRL Events, Marketing, New Business Sales, People & Ops, Product-Led Sales East, Product-Led Sales West, Support, Talent, Website, YouTube.

## Summary

- **50** teams on posthog.com/teams.
- **25** engineering teams own at least one product directory in this repo.
- **11** ship both MCP tools and skills.
- **9** ship MCP tools but no skills — primary gap to close.
- **1** ships skills but no MCP tools (Growth).
- **4** ship neither (Warehouse Sources, Data Tools, Ingestion, ClickHouse).
- **10** engineering teams from the public page have no product directory in this repo (work elsewhere).
- **15** non-engineering teams on the public page (out of scope).

## Top opportunities

1. **MCP-only teams without any skills** (biggest leverage — they already invested in MCP surface):
   Error Tracking, Platform Features, Workflows, Surveys, Customer Analytics, Conversations, Batch Exports, Analytics Platform, Data Modeling.
2. **Growth** has a skill (`diagnosing-sdk-health`) but no `mcp/tools.yaml` — could expose growth/onboarding actions over MCP.
3. **Warehouse Sources, Data Tools, Ingestion** have no agent surface at all yet.
