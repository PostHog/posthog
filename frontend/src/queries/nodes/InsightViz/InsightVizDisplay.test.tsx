import { InsightType } from '~/types'

import { shouldShowDashboardInsightRefreshHint } from './InsightVizDisplay'

describe('InsightVizDisplay', () => {
    it.each([
        {
            name: 'dashboard tile never got numbers back (e.g. cache miss) → suggest refresh',
            params: {
                isInDashboardContext: true,
                doNotLoad: false,
                activeView: InsightType.TRENDS,
                insightData: { result: null },
            },
            expected: true,
        },
        {
            name: 'dashboard tile has no insight payload yet → suggest refresh',
            params: {
                isInDashboardContext: true,
                doNotLoad: false,
                activeView: InsightType.TRENDS,
                insightData: {},
            },
            expected: true,
        },
        {
            name: 'dashboard tile payload present but result still empty → suggest refresh',
            params: {
                isInDashboardContext: true,
                doNotLoad: false,
                activeView: InsightType.TRENDS,
                insightData: { result: undefined },
            },
            expected: true,
        },
        {
            name: 'date range genuinely has no events (empty series) → do not hijack with refresh hint',
            params: {
                isInDashboardContext: true,
                doNotLoad: false,
                activeView: InsightType.TRENDS,
                insightData: { result: [] },
            },
            expected: false,
        },
        {
            name: 'viewing the insight outside a dashboard → no dashboard-only hint',
            params: {
                isInDashboardContext: false,
                doNotLoad: false,
                activeView: InsightType.TRENDS,
                insightData: { result: null },
            },
            expected: false,
        },
        {
            name: 'deferred tile not loading yet → do not prompt refresh',
            params: {
                isInDashboardContext: true,
                doNotLoad: true,
                activeView: InsightType.TRENDS,
                insightData: { result: null },
            },
            expected: false,
        },
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
})
