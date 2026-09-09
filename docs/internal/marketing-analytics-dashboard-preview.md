# Marketing analytics dashboard preview

The `new-marketing-analytics-dashboard` flag replaces the Dashboard tab with a website-first view and moves the existing advertising dashboard to Ad performance. With the flag off, existing navigation and onboarding remain available.

## Navigation and reusable components

- Acquisition: Web Analytics overview, a Trends visitor chart, and a channel table with visitors, sessions, and pageviews.
- Engagement: session duration and bounce rate, using session properties. Page reports remain available through Web Analytics.
- Retention: the existing Retention explorer and its cohort semantics.
- Conversion: the existing Attribution explorer, model comparison, and conversion paths.
- Revenue: the existing attribution table restricted to valid event/action goals marked as revenue. Select one goal at a time to avoid double-counting overlapping goals. Warehouse goals remain in Ad performance.
- Ad performance: existing campaign table, cost chart, and overview. Include conversion goals defaults on and controls displayed goal metrics. It does not delete goals or bypass their backend computations.
- Setup: existing suggestions, integrations, goals, mapping, and attribution settings.

The new dashboard is accessible without ad integrations. Missing integrations are explained inline; Ad performance links to setup. Existing explorer URLs select the corresponding dashboard section.

## Metric definitions

Visitors are distinct people who generated a pageview. Sessions count distinct sessions containing a pageview; pageviews count events. Breakdown values use session entry properties. UTM source and referring domain are separate dimensions. A visitor may appear in multiple breakdown rows.

Table values use the query runner's period-wide aggregate, not a sum of daily distinct counts. Previous-period results are aligned by breakdown and metric, independent of result ordering. Missing values display a dash; numeric zero remains zero.

Retention keeps the existing cohort definition. It is not a cumulative “returned at any point in 7/30 days” metric. Revenue retains the existing attribution model and window semantics. Advertising spend is not mixed into raw UTM-source traffic rows.

## Local verification

Use a dedicated demo project and the existing `generate_marketing_demo_data` command. Its event generator can also populate recent activity independently without replacing configured warehouse sources. The full command recreates demo source fixtures and should not target a project with integrations to preserve.

Check the date range, Exclude test accounts, person properties mode, and precompute freshness when synthetic events are present but charts are empty. The event generator writes person details on events. Precomputed historical buckets may need revalidation after a historical seed.

Verify acquisition totals and breakdowns, date comparison, engagement, cohort retention, conversion-goal selection, revenue-goal selection, and Ad performance with goals on and off. Also verify an unintegrated project enters the dashboard directly.

## Follow-up implementation order

1. Add pages per session and richer engagement metrics, reusing Web Analytics queries and keeping definitions explicit.
2. Create 1-3 initial conversion goals from observed eligible events, with idempotency and no duplication of existing goals. Reuse setup suggestions for cases where events are missing or ambiguous.
3. Extend revenue to warehouse goals and common spend/attribution breakdowns before adding blended ROAS.
4. Treat Page visibility as a separate feature, with its own data sources, definitions, and verification.

Automatic goal creation and Page visibility are not part of this preview. New-visitor counts and richer engagement measures remain follow-up work.
