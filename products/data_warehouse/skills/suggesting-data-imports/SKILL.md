---
name: suggesting-data-imports
description: 'Use when the user asks about revenue, payments, subscriptions, billing, CRM deals, support tickets, production database tables, or other data that PostHog does not collect natively. Also use when a query fails because a table does not exist or returns no results for expected external data. The data warehouse can import from SaaS tools (Stripe, Hubspot, etc.), production databases (Postgres, MySQL, BigQuery, Snowflake), and other arbitrary data sources. Covers checking existing sources, identifying the right source type, and guiding the setup.'
---

# Suggesting data imports

This skill helps identify when data the user needs lives outside PostHog and guides them toward importing it via the data warehouse. The key insight is recognizing the gap — then connecting it to the right source type.

## What PostHog collects natively

PostHog collects product analytics events, persons, sessions, and groups via its SDKs. Additional products are available but must be enabled: session replay, feature flags, experiments, surveys, web analytics, error tracking, LLM analytics, conversations, logs, revenue analytics, workflows, CDP destinations, and batch exports. PostHog does **not** collect external business data like payments, subscriptions, CRM records, support tickets from other systems, or production database tables — that data must be imported via the data warehouse.

## When to use this skill

- A HogQL query fails because a table doesn't exist
- The user asks about data from an external system (Stripe, Hubspot, Salesforce, etc.)
- The user wants to correlate PostHog analytics with business data (revenue, support tickets, CRM records, etc)
- The user asks "how do I get my X data into PostHog?"
- Analysis requires joining PostHog events with external data
- The user asks about exporting PostHog data for comparison elsewhere (in a google sheet, external warehouse, etc)

## Workflow

### 1. Understand what data is missing

Listen for signals that the user needs external data:

- They mention a specific tool or system (Stripe, Hubspot, Zendesk, their production database, etc.)
- A query references a table that doesn't exist in PostHog
- They want to analyze something PostHog doesn't track natively (revenue, support tickets, CRM deals, etc.)

If a query failed, check the error — if it's "table not found" or similar, the data likely needs to be imported.

### 2. Check what's already connected

Call `posthog:external-data-sources-list` to see existing sources. The data might already be imported but the user doesn't know the table name or prefix.

If a source exists for the system they're asking about, call `posthog:external-data-schemas-list` to show the available tables. The data might be there but under a different name or prefix.

Also call `posthog:read-data-warehouse-schema` to see all queryable tables — the data might already be available as a view or joined table.

### 3. Identify the right source type

If the data isn't imported yet, call `posthog:external-data-sources-wizard` to see available source types. Match the user's need to a source:

**Common patterns:**

| User wants                 | Source type                                    | Key tables                                  |
| -------------------------- | ---------------------------------------------- | ------------------------------------------- |
| Revenue / payment data     | Stripe, Chargebee, Shopify                     | charges, subscriptions, invoices, customers |
| CRM / sales pipeline       | Hubspot, Salesforce, Attio                     | contacts, deals, companies                  |
| Support tickets            | Zendesk                                        | tickets, users, organizations               |
| Product data from their DB | Postgres, MySQL, BigQuery, Snowflake, Redshift | user's own tables                           |
| Marketing / ads            | Google Ads, Meta Ads, LinkedIn Ads, TikTok Ads | campaigns, ad_groups, ads                   |
| Email marketing            | Mailchimp, Klaviyo                             | campaigns, lists, subscribers               |
| Project management         | Linear                                         | issues, projects                            |
| Error tracking (external)  | Sentry                                         | issues, events                              |

### 4. Suggest the import

Present the recommendation concisely:

- What source type to connect
- What tables would become available
- How this enables the analysis they want

Example: "Your Stripe data isn't in PostHog yet. If you connect a Stripe source, you'll get tables like `charges`, `subscriptions`, and `customers` that you can join with PostHog events to analyze revenue by user behavior."

### 5. Offer to set up the source

If the user wants to proceed, hand off to the **`setting-up-a-data-warehouse-source`** skill — it covers the full
three-step flow (wizard → db-schema → create), sync-type selection, webhook registration, and prefix guidance.
Do not duplicate that workflow here.

### 6. Show what's possible after import

Once connected, help the user write their first query joining PostHog data with the imported data. Use `posthog:execute-sql` to demonstrate.

Common join patterns:

- Join Stripe customers with PostHog persons on email: `SELECT * FROM stripe_customers sc JOIN persons p ON sc.email = p.properties.$email`
- Join CRM deals with events: correlate product usage with sales outcomes
- Join support tickets with session recordings: find recordings for users who filed tickets

## Important notes

- **Don't guess table names.** Always check `posthog:read-data-warehouse-schema` and `posthog:external-data-schemas-list` before saying data doesn't exist.
- **Check prefixes.** Imported tables are often prefixed (e.g. `stripe_charges` not `charges`). The user might not know the prefix.
- **OAuth sources require the UI.** Some sources (Google Ads, Meta Ads, Hubspot with OAuth) require browser-based OAuth flows. You can't complete these via MCP — direct the user to the PostHog UI at `/data-warehouse/new`.
- **Not all systems are supported.** If the user's system isn't in the wizard list, suggest using Postgres/MySQL as a bridge if they can export to a database, or mention that custom sources can be requested.

## Related tools

- `posthog:external-data-sources-list`: Check existing source connections
- `posthog:external-data-schemas-list`: Check what tables are already imported
- `posthog:read-data-warehouse-schema`: See all queryable tables including views
- `posthog:external-data-sources-wizard`: Get available source types
- `posthog:execute-sql`: Run queries to demonstrate what's possible

## Related skills

- **`setting-up-a-data-warehouse-source`**: Full source creation workflow — hand off here once the user decides to connect a source
