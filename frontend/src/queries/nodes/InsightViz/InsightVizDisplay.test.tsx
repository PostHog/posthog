import { InsightType } from '~/types'

import { resolveInFlightQueryState, shouldShowDashboardInsightRefreshHint } from './InsightVizDisplay'

const ALL_INSIGHT_TYPES = Object.values(InsightType) as InsightType[]
/** Insight types that use the dashboard refresh hint (excludes web analytics — separate UX). */
const DASHBOARD_HINT_INSIGHT_TYPES = ALL_INSIGHT_TYPES.filter((t) => t !== InsightType.WEB_ANALYTICS)

describe('InsightVizDisplay', () => {
    it.each([
        ...DASHBOARD_HINT_INSIGHT_TYPES.flatMap((activeView) => [
            {
                name: `dashboard tile never got numbers back (e.g. cache miss) [${activeView}]`,
                params: {
                    isInDashboardContext: true,
                    doNotLoad: false,
                    activeView,
                    insightData: { result: null },
                },
                expected: true,
            },
            {
                name: `dashboard tile has no insight payload yet [${activeView}]`,
                params: {
                    isInDashboardContext: true,
                    doNotLoad: false,
                    activeView,
                    insightData: {},
                },
                expected: true,
            },
            {
                name: `dashboard tile payload present but result still empty [${activeView}]`,
                params: {
                    isInDashboardContext: true,
                    doNotLoad: false,
                    activeView,
                    insightData: { result: undefined },
                },
                expected: true,
            },
            {
                name: `date range genuinely has no events (empty series) — do not hijack [${activeView}]`,
                params: {
                    isInDashboardContext: true,
                    doNotLoad: false,
                    activeView,
                    insightData: { result: [] },
                },
                expected: false,
            },
        ]),
        ...ALL_INSIGHT_TYPES.flatMap((activeView) => [
            {
                name: `viewing the insight outside a dashboard — no dashboard-only hint [${activeView}]`,
                params: {
                    isInDashboardContext: false,
                    doNotLoad: false,
                    activeView,
                    insightData: { result: null },
                },
                expected: false,
            },
            {
                name: `deferred tile not loading yet — do not prompt refresh [${activeView}]`,
                params: {
                    isInDashboardContext: true,
                    doNotLoad: true,
                    activeView,
                    insightData: { result: null },
                },
                expected: false,
            },
        ]),
        {
            name: 'web analytics on a dashboard → use its own UX, not this hint',
            params: {
                isInDashboardContext: true,
                doNotLoad: false,
                activeView: InsightType.WEB_ANALYTICS,
                insightData: { result: null },
            },
            expected: false,
        },
    ])('shouldShowDashboardInsightRefreshHint: $name', ({ params, expected }) => {
        expect(shouldShowDashboardInsightRefreshHint(params)).toBe(expected)
    })

    it.each([
        {
            name: 'current query failed — surface the error, not loading',
            params: { erroredQueryId: 'q1', queryId: 'q1', isFunnels: true, hasFunnelResults: false },
            expected: { displayErroredQueryId: 'q1', funnelResultsStale: false },
        },
        {
            name: 'superseded query failed after a newer one started — drop the stale error, keep loading',
            params: { erroredQueryId: 'old', queryId: 'new', isFunnels: true, hasFunnelResults: false },
            expected: { displayErroredQueryId: null, funnelResultsStale: true },
        },
        {
            name: 'late failure lands after the newer query already returned results — show the chart',
            params: { erroredQueryId: 'old', queryId: 'new', isFunnels: true, hasFunnelResults: true },
            expected: { displayErroredQueryId: null, funnelResultsStale: false },
        },
        {
            name: 'no failure — nothing to drop',
            params: { erroredQueryId: null, queryId: 'q1', isFunnels: true, hasFunnelResults: false },
            expected: { displayErroredQueryId: null, funnelResultsStale: false },
        },
        {
            name: 'stale failure on a non-funnel insight — no funnel-specific loading gap',
            params: { erroredQueryId: 'old', queryId: 'new', isFunnels: false, hasFunnelResults: false },
            expected: { displayErroredQueryId: null, funnelResultsStale: false },
        },
    ])('resolveInFlightQueryState: $name', ({ params, expected }) => {
        expect(resolveInFlightQueryState(params)).toEqual(expected)
    })
})
