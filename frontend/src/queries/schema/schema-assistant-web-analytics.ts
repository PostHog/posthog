import type { EventPropertyFilter, PersonPropertyFilter } from '~/types'

import { AssistantDateRangeFilter } from './schema-assistant-queries'
import {
    CompareFilter,
    NodeKind,
    WebAnalyticsConversionGoal,
    WebAnalyticsPropertyFilters,
    WebStatsBreakdown,
    WebVitalsMetric,
    WebVitalsPercentile,
} from './schema-general'
import { non_negative_integer, positive_integer } from './type-utils'

export interface WebAnalyticsAssistantFilters {
    date_from?: string | null
    date_to?: string | null
    properties: WebAnalyticsPropertyFilters
    doPathCleaning?: boolean
    compareFilter?: CompareFilter | null
}

/**
 * Shared filter set across all web-analytics assistant queries.
 *
 * Mirrors `WebAnalyticsQueryBase` but drops noisy fields agents shouldn't set
 * (`samplingFactor`, `aggregation_group_type_index`, `dataColorTheme`,
 * deprecated/legacy options).
 */
export interface AssistantWebAnalyticsQueryBase {
    /**
     * Date range for the query. Defaults to the last 7 days when omitted.
     * Keep ranges short — the backend has no upper bound and large windows on
     * the slow path (e.g. with `conversionGoal` or `includeAvgTimeOnPage`) can
     * be expensive.
     */
    dateRange?: AssistantDateRangeFilter

    /**
     * Property filters applied to the query. Accepts event, person, session,
     * or cohort filters.
     *
     * @default []
     */
    properties?: WebAnalyticsPropertyFilters

    /**
     * Compare the current period to a prior period. Disabled by default.
     * Enabling roughly doubles query cost — leave it off unless the user
     * explicitly asks for a period-over-period comparison.
     */
    compareFilter?: CompareFilter

    /**
     * Apply the team's path-cleaning rules to URL-style breakdowns.
     * @default false
     */
    doPathCleaning?: boolean

    /**
     * Exclude internal and test users by applying the team's test-account filter.
     * @default false
     */
    filterTestAccounts?: boolean

    /**
     * Conversion goal — pass an `actionId` (must belong to the current project)
     * or a `customEventName`. Adds conversion columns to the response. Disables
     * the pre-aggregated fast path — only set when the user explicitly asks
     * about a conversion.
     */
    conversionGoal?: WebAnalyticsConversionGoal | null
}

/**
 * High-level web-analytics KPIs over a period: visitors, pageviews, sessions,
 * average session duration, and bounce rate. Returns a small list of metric
 * tuples with optional period-over-period comparison.
 *
 * Use this when the user asks "how is the site doing?", "what are the topline
 * web numbers?", or wants a snapshot of overall traffic health.
 */
export interface AssistantWebOverviewQuery extends AssistantWebAnalyticsQueryBase {
    kind: NodeKind.WebOverviewQuery
}

/**
 * Tabular web-analytics breakdown — top pages, UTMs, devices, browsers,
 * countries, etc. — with visitors, pageviews, and optional bounce rate /
 * average time on page columns.
 *
 * This is the right query for "top pages with bounce rate" (set
 * `breakdownBy=Page` and `includeBounceRate=true`) and for entry/exit-page
 * navigation analysis (`breakdownBy=InitialPage|ExitPage|PreviousPage`).
 */
export interface AssistantWebStatsTableQuery extends AssistantWebAnalyticsQueryBase {
    kind: NodeKind.WebStatsTableQuery

    /**
     * Required. Property to break down the table by. The full enum covers
     * path-style (`Page`, `InitialPage`, `ExitPage`, `PreviousPage`),
     * marketing/source (UTM source/medium/campaign/term/content, channel,
     * referring domain), audience/device (browser, OS, device type, viewport),
     * and geography (country, region, city, timezone, language). Path-style
     * breakdowns pair naturally with `includeBounceRate` /
     * `includeAvgTimeOnPage`.
     */
    breakdownBy: WebStatsBreakdown

    /**
     * Add a bounce-rate column. Most useful with a path-style breakdown.
     * @default false
     */
    includeBounceRate?: boolean

    /**
     * Add an average-time-on-page column. Implies a Page-style breakdown.
     * Disables the pre-aggregated fast path.
     * @default false
     */
    includeAvgTimeOnPage?: boolean

    /**
     * When using a path-style breakdown (`Page`, `InitialPage`, `ExitPage`,
     * `PreviousPage`), concatenate host + pathname so the same path on
     * different hosts is counted separately.
     * @default false
     */
    includeHost?: boolean

    /**
     * Maximum rows to return. Prefer 10–25 unless the user explicitly asks
     * for more. Hard ceiling enforced at the wrapper.
     *
     * @maximum 200
     */
    limit?: positive_integer

    /**
     * Pagination offset.
     */
    offset?: non_negative_integer
}

/**
 * Per-page Core Web Vitals breakdown for one metric at one percentile. Returns
 * the pages bucketed into `good` / `needs_improvements` / `poor` bands, with
 * each page's value — mirrors the in-product **Web vitals** tab.
 *
 * Use this when the user asks "which pages are slow?", "where is our LCP/INP/
 * CLS/FCP bad?", or wants a page-level performance audit. Run it once per
 * metric. For a site-wide trend of a vitals metric over time, use
 * `query-trends` on the `$web_vitals` event instead.
 */
export interface AssistantWebVitalsPathBreakdownQuery {
    kind: NodeKind.WebVitalsPathBreakdownQuery

    /**
     * Date range for the query. Defaults to the last 7 days when omitted —
     * a good window for a stable percentile.
     */
    dateRange?: AssistantDateRangeFilter

    /**
     * Property filters applied to the query. Accepts event and person filters
     * only (the query runner ignores session and cohort filters) — e.g. an
     * event filter on `$host` to scope to one domain, or on `$device_type` to
     * isolate mobile.
     *
     * @default []
     */
    properties?: (EventPropertyFilter | PersonPropertyFilter)[]

    /**
     * Apply the team's path-cleaning rules to the returned paths.
     * @default false
     */
    doPathCleaning?: boolean

    /**
     * Exclude internal and test users by applying the team's test-account filter.
     * @default false
     */
    filterTestAccounts?: boolean

    /**
     * Required. Which Core Web Vital to break down by: `LCP` (load, ms),
     * `INP` (interactivity, ms), `CLS` (layout stability, unitless score),
     * or `FCP` (first paint, ms).
     */
    metric: WebVitalsMetric

    /**
     * Required. Percentile to aggregate each page's samples at. Use `p75`
     * unless the user asks otherwise — the Google bands are defined at p75.
     */
    percentile: WebVitalsPercentile

    /**
     * Required. `[good, poor]` band boundaries for the chosen metric. Values
     * below `good` are good, above `poor` are poor, in between need
     * improvement. Use the standard Google thresholds unless the user supplies
     * their own: LCP `[2500, 4000]`, INP `[200, 500]`, CLS `[0.1, 0.25]`,
     * FCP `[1800, 3000]`.
     */
    thresholds: [number, number]
}
