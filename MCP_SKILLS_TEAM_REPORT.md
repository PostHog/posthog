# MCP Tools & Skills — Team Coverage Report

Generated 2026-05-07. Source of truth: `products/*/product.yaml` (owner field) cross-referenced with the team list at https://posthog.com/teams.

## Methodology

- Team list pulled from https://posthog.com/teams (50 teams).
- Product ownership read from each `products/*/product.yaml` `owners:` field.
- MCP tool count = entries with `enabled: true` in `products/*/mcp/tools.yaml`.
- Skill count = `SKILL.md` files under `products/*/skills/**`.
- Non-engineering teams (sales, marketing, ops, etc.) and teams whose code lives outside this monorepo (Client Libraries, ClickHouse infra, Cloud Foundations, etc.) are listed separately as "out of scope".

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

Notes:
- "Flags Platform" appears on posthog.com/teams but no product.yaml maps to a `team-flags-platform` owner — ownership in this repo currently rolls up to `team-feature-flags`.
- The `core_events` product is owned by `team-events`, which does not appear on the public teams page; treating it as part of Ingestion / Product Analytics scope.
- `live_debugger` is owned by `clickhouse` (infra team) and currently ships no MCP tools or skills.

## Teams on posthog.com/teams with no product directory in this repo

These teams either don't ship product code in `posthog/posthog`, are non-engineering, or work in separate repos. They are not expected to ship MCP tools or skills here.

- Billing
- Blitzscale
- Client Libraries (SDKs live in `posthog-js`, `posthog-python`, etc.)
- Cloud Foundations
- ClickHouse (infra; only owns `live_debugger` here)
- Customer Success
- Demand Gen
- Docs & Wizard
- Editorial
- Forward Deployed Engineering
- Graphics
- IRL Events
- Marketing
- New Business Sales
- Onboarding (no `product.yaml` owner found)
- People & Ops
- Platform UX
- PostHog Code
- Product-Led Sales East
- Product-Led Sales West
- Security
- Support
- Talent
- Website
- YouTube

## Summary

- **24** engineering teams own product directories in this repo.
- **11** ship both MCP tools and skills.
- **9** ship MCP tools but no skills — primary gap to close.
- **1** ships skills but no MCP tools (Growth).
- **3** ship neither (Warehouse Sources, Data Tools, Ingestion).

## Top opportunities

1. **MCP-only teams without any skills** (biggest leverage — they already invested in MCP surface):
   Error Tracking, Platform Features, Workflows, Surveys, Customer Analytics, Conversations, Batch Exports, Analytics Platform, Data Modeling.
2. **Growth** has a skill (`diagnosing-sdk-health`) but no `mcp/tools.yaml` — could expose growth/onboarding actions over MCP.
3. **Warehouse Sources, Data Tools, Ingestion** have no agent surface at all yet.
