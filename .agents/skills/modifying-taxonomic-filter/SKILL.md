---
name: modifying-taxonomic-filter
description: Guides safe, evidence-led changes to the TaxonomicFilter, PostHog's picker for events, actions, properties, cohorts, and more. Use when adding features, fixing bugs, removing groups or tabs, changing search, ordering, recents, pinning, empty states, loading or performance, or refactoring the picker. Indexes how users actually pick, known failure modes, the feature inventory, design principles, contested decisions, where to find evidence, and how to measure a change.
---

# Modifying the TaxonomicFilter

The TaxonomicFilter is the picker users hit to choose any "thing PostHog knows about": events, properties, actions, cohorts, groups.
It is the on-ramp into almost every analytics, flags and replay configuration.
Code lives in `frontend/src/lib/components/TaxonomicFilter/`.

This file is an index.
Read it fully, then load only the references your change needs.
The references hold the detail and the evidence.

## Three guardrails

1. **Decide with evidence, not taste.**
   Everyone who has worked on this picker has strong opinions, and some of them are wrong.
   Check a claim against [product-reality](references/product-reality.md) and [evidence-sources](references/evidence-sources.md) before acting on it, including claims in issues, Slack, or this skill.
2. **Demoting what users actually pick is a regression**, even with every test green.
   Ordering, promotion, position-0 and default-tab changes need explicit human sign-off.
3. **Telemetry is a public contract.**
   Dashboards and replay scanners read these events.
   Never rename or repurpose a property silently.
   `telemetryContract.test.ts` fails when a capture call and the contract disagree, so update the contract in the same PR.
   See [telemetry-contract](references/telemetry-contract.md).

## The picture in five lines (refreshed 2026-10-15)

- Most engaged legacy opens end in a selection (~85%), and most never touch a category tab (~96%).
- The Suggested view carries about 70% of legacy selections.
  Just over half of those come from recents.
- Position matters: ~52% of legacy picks are row 0, ~85% are in the top three.
- The biggest failure is a category picked first, then a search that finds nothing.
  Most empty searches are the right word in the wrong tab.
- Customers report broken UI and missing items far more than slowness.

Detail, windows and caveats: [product-reality](references/product-reality.md).
These numbers are a snapshot.
For current values, run the `taxonomic_filter_*` metrics in the PostHog data catalog (see [refreshing-product-reality](references/refreshing-product-reality.md#live-metrics)).

## Route by what you are changing

| You are changing                            | Read first                                                                                                                                                       |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ordering, promotion, Suggested, default tab | [product-reality](references/product-reality.md), [design-principles](references/design-principles.md), [contested-decisions](references/contested-decisions.md) |
| Adding, removing or hiding a group or tab   | [feature-inventory](references/feature-inventory.md), [call-sites](references/call-sites-and-blast-radius.md)                                                    |
| Search, empty states, no-results recovery   | [failure-modes](references/failure-modes.md), [design-principles](references/design-principles.md)                                                               |
| Recents, pinning, remembered state          | [contested-decisions](references/contested-decisions.md), [design-principles](references/design-principles.md)                                                   |
| Loading, latency, pagination, errors        | [performance](references/performance.md), [failure-modes](references/failure-modes.md)                                                                           |
| Telemetry or dashboards                     | [telemetry-contract](references/telemetry-contract.md), [measuring-changes](references/measuring-changes.md)                                                     |
| Any refactor                                | [architecture](references/architecture.md), [common-pitfalls](references/common-pitfalls.md), [testing-patterns](references/testing-patterns.md)                 |
| A bug report you can't reproduce            | [call-sites](references/call-sites-and-blast-radius.md) (confirm the call site and props first)                                                                  |
| Deciding whether a change is worth it       | [evidence-sources](references/evidence-sources.md), [measuring-changes](references/measuring-changes.md)                                                         |

## Working loop

1. **State the user problem.**
   Which users, which call site, what goes wrong.
   Find it in the evidence, not only in the request.
   See [evidence-sources](references/evidence-sources.md).
2. **Size it.**
   Use ratios from telemetry.
   A change that helps 0.1% of opens and risks the Suggested view is not worth it.
3. **Check the principles and contested decisions** that apply.
   If your change reverses a documented decision, say so and bring evidence.
4. **Lock behavior with React Testing Library tests** at the call sites you touched.
   Agents find this component confusing; RTL tests are the fastest guard.
   See [testing-patterns](references/testing-patterns.md).
5. **Decide how you will know it worked** before merging.
   Ship ordering or default changes behind a flag with a metric and a guardrail.
   See [measuring-changes](references/measuring-changes.md).

## Pre-change checklist

- [ ] The user problem is linked to evidence (telemetry, replay, ticket)
- [ ] Every call site the change reaches is tested, including ones that mount `TaxonomicFilter` directly
- [ ] Telemetry payloads still match the contract
- [ ] Ordering, promotion, position-0 or default tab: human sign-off
- [ ] Search or loading: plan boundary verified, optional requests don't delay results
- [ ] A success metric and a guardrail metric are named
- [ ] If you changed the facts, update [product-reality](references/product-reality.md)

```bash
hogli test frontend/src/lib/components/TaxonomicFilter/
```

Keep this skill honest: if the data contradicts it, fix the skill in the same PR.
Refresh numbers with [refreshing-product-reality](references/refreshing-product-reality.md) when they are older than about three months.
