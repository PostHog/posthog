import { InsightType } from '~/types'

import { shouldShowInsightRefreshHint } from './InsightVizDisplay'

const ALL_INSIGHT_TYPES = Object.values(InsightType) as InsightType[]
/** Insight types that use the refresh hint (excludes web analytics — separate UX). */
const HINT_INSIGHT_TYPES = ALL_INSIGHT_TYPES.filter((t) => t !== InsightType.WEB_ANALYTICS)

describe('InsightVizDisplay', () => {
    it.each([
        ...HINT_INSIGHT_TYPES.flatMap((activeView) => [
            {
                name: `never got numbers back (e.g. cache miss) [${activeView}]`,
                params: { doNotLoad: false, activeView, insightData: { result: null } },
                expected: true,
            },
            {
                name: `no insight payload yet [${activeView}]`,
                params: { doNotLoad: false, activeView, insightData: {} },
                expected: true,
            },
            {
                name: `payload present but result still undefined [${activeView}]`,
                params: { doNotLoad: false, activeView, insightData: { result: undefined } },
                expected: true,
            },
            {
                name: `date range genuinely has no events (empty series) — do not hijack [${activeView}]`,
                params: { doNotLoad: false, activeView, insightData: { result: [] } },
                expected: false,
            },
            {
                name: `deferred tile not loading yet — do not prompt refresh [${activeView}]`,
                params: { doNotLoad: true, activeView, insightData: { result: null } },
                expected: false,
            },
        ]),
        {
            name: 'web analytics → use its own UX, not this hint',
            params: { doNotLoad: false, activeView: InsightType.WEB_ANALYTICS, insightData: { result: null } },
            expected: false,
        },
    ])('shouldShowInsightRefreshHint: $name', ({ params, expected }) => {
        expect(shouldShowInsightRefreshHint(params)).toBe(expected)
    })
})
