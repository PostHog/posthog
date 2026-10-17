---
name: preparing-customer-calls
description: >
  Prepare a PostHog staff member for a customer call or chat: resolve the customer organization,
  pull spend, product usage, tool stack, recorded calls, account notes, shared and internal Slack threads from the last 60 days,
  and write a call prep notebook in PostHog project 2 shaped around one focus area
  (for example data warehouse, product analytics, semantic layer, data analysis, error tracking, or MCP observability).
  Use when asked to prep for a customer call, build a customer brief or account prep sheet, or "get me up to speed on <customer> before I talk to them".
  Internal-only: reads cross-customer billing, CRM, call and Slack data in project 2;
  never copy customer names, numbers, or conversation text into public artifacts (PRs, issues, commits).
---

# Preparing customer calls

The job: a staff member is about to talk to a customer.
Give them one notebook that tells them who the customer is, what they pay and use,
what is going on with them right now, and what to ask about the focus area.
The reader skims it in five minutes before the call, so lead with conclusions and keep evidence one click away.

All sources live in PostHog project 2 (US) and are read with the PostHog MCP.
The data catalog metrics table is the only exception: it needs `hogli metabase:query` from a repository checkout.

## 1. Get the two inputs

You need the **customer** (organization name, brand, domain, or org id) and the **focus area**.
If either is missing from the request, ask the user for it before you query anything.
Use your harness's question tool when it has one (for example `AskUserQuestion` in Claude Code). Otherwise ask in chat and wait for the answer.
Offer the common focus areas as options (data warehouse, product analytics, semantic layer, error tracking) and let "Other" cover the rest.
Accept free text such as "MCP observability" or "data analysis".
Map the focus area to its signals with [references/focus-areas.md](references/focus-areas.md).

## 2. Resolve the organization

Search `org_universe` by `organization_name` **and** `company_domain`, because the billing name and the brand often differ.
Then confirm with `accounts-list` (`search` matches names, external ids, and email domains).

- More than one match is normal. Prefer the org with spend, an owner, or a shared channel.
  Name the other matches in the notebook header so the reader can correct you.
- If no org has spend and the user named a company, ask before you continue.
- Record these ids for later steps: `organization_id`, the Customer Analytics account `id`, `region`, the shared Slack channel id, `sfdc_account_id`, and the account's email domains.

Queries for every step are in [references/data-sources.md](references/data-sources.md).

## 3. Collect the evidence

Run independent queries in parallel. Use a 60-day window for conversations, and all-time for account history.

| Section                        | Primary sources                                                                                                                  |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| Company and commercials        | `org_universe` (plan, usage MRR, forecast, contract, credits, owners, firmographics, health)                                     |
| Products used heavily          | `invoiced_mrr_m1_per_product` and `forecasted_mrr_per_product` in `org_universe`, `account_health_scores_v4`, `v_mcp_tool_calls` |
| Focus area                     | the signals in [references/focus-areas.md](references/focus-areas.md)                                                            |
| Stack, architecture, workflows | connected-tools tables, Gong summaries, account notebooks, Vitally notes, Slack text                                             |
| What happened lately           | shared Slack channel, internal Slack channels, Gong calls, `system.support_tickets`, account notebooks                           |

Rules that keep the sheet trustworthy:

- **Spend:** annual credit customers show a small `mrr` (the plan fee only). Report `usage_mrr`, `forecasted_usage_mrr`, `contract_credit_amount`, and the contract dates instead.
  Do not use `internal_org_mrr_by_product`; its values do not match invoices.
- **Every "none found" is a query result.** Do not write "no tickets" or "no notebooks" until a query for that org returned nothing.
- **Every link comes from data.** Build Slack permalinks from the exact `ts` of the message you read. Never type a timestamp by hand.
- **Common-word names produce false matches.** A customer called "Beacon" or "Double" matches "beacon API" and "double check".
  Read the snippet before you attribute an internal message to the customer.
- **Do not merge two customers' facts.** When you test queries on one org and then run another, re-read every fact against the current org id.
- **Customer people:** external Slack users have no `real_name`. Get names from replies that address them, not from guesses.
- **Customer vs scout activity:** count only `is_customer_driven = 1` MCP rows as customer adoption. Scout runs on their project are a separate signal.
- **Freshness:** the Slack mirror starts on 2026-06-04, Vitally and Zendesk syncs lag or pause, and project 2 shows times in Pacific time.
  Say which sources were stale in the notebook header.

## 4. Write the notebook

Create it with `notebooks-create-markdown` in project 2.
Title: `Call prep: <brand> (<org name if different>) · <focus area> · <YYYY-MM-DD>`.
Put the header and the TL;DR in the initial markdown, then add one cell per section with `notebooks-add-cell`.

1. **Header:** focus, window, org id, region, links (account, org group, Salesforce, shared channel), name-match note, freshness note.
2. **TL;DR for the call:** five bullets at most. Who they are, what they pay, where the focus area stands, their mood, the best opening.
3. **Company and commercials:** prose, then a SQL cell for the account snapshot (table, transposed) and a SQL cell for spend by product (bar chart).
4. **Products they use heavily:** prose, then a SQL cell for agent and MCP usage when it is material.
5. **Focus area:** where they are, evidence of need, what they already built, limits, and 4–6 questions to ask. This is the section the reader came for.
6. **Stack and workflows:** tools they name, how data moves, what stays outside PostHog, then a SQL cell for connected tools.
7. **Last 60 days:** shared channel newest first, recorded calls, internal threads. One line per thread, each with its permalink.
8. **Open threads and risks:** one item per open topic, with links to the unanswered message, the full thread, any internal escalation, and an open ticket (`generate-app-url` with `/support/tickets/{ticketId}`).
   Link a reply inside a thread as `p<reply ts>?thread_ts=<thread ts>&cid=<CHANNEL_ID>`.
   Then **Sources checked** with what each source returned.

Keep SQL cells for numbers a reader may want to re-run. Write prose for conversations; do not paste raw message dumps.
Fix a wrong statement in place with `notebooks-update-cell` (markdown cells take `markdown`), so the link stays the same.

## 5. Hand over

Reply with the notebook link, the org you chose and why, and anything you could not check.
The notebook stays internal to project 2.
Do not publish it as an artifact or paste its content into a public place.
