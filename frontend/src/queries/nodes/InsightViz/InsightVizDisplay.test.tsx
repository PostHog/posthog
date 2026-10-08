import { InsightType } from '~/types'

import { hasResultRows, shouldShowAIAnalysisSection, shouldShowDashboardInsightRefreshHint } from './InsightVizDisplay'

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

    const AI_SECTION_BASE = {
        editMode: false,
        embedded: false,
        inSharedMode: false,
        hasQuerySource: true,
        insightDataLoading: false,
        hasBlockingEmptyState: false,
        hasResults: true,
    }

    it.each([
        { name: 'query succeeded with results', params: {}, expected: true },
        { name: 'query failed or timed out', params: { hasBlockingEmptyState: true }, expected: false },
        { name: 'query came back without results', params: { hasResults: false }, expected: false },
        {
            name: 'query still in flight — keep the section up so it does not appear late',
            params: { insightDataLoading: true, hasBlockingEmptyState: true, hasResults: false },
            expected: true,
        },
        { name: 'editing the insight', params: { editMode: true }, expected: false },
        { name: 'embedded', params: { embedded: true }, expected: false },
        { name: 'shared externally', params: { inSharedMode: true }, expected: false },
        { name: 'not an insight query node', params: { hasQuerySource: false }, expected: false },
    ])('shouldShowAIAnalysisSection: $name', ({ params, expected }) => {
        expect(shouldShowAIAnalysisSection({ ...AI_SECTION_BASE, ...params })).toBe(expected)
    })

    it.each([
        { name: 'trends series came back', insightData: { result: [{ label: 'Pageview', count: 3 }] }, expected: true },
        { name: 'query succeeded with no rows', insightData: { result: [] }, expected: false },
        { name: 'query succeeded with no rows under results', insightData: { results: [] }, expected: false },
        {
            name: 'all-zero series still counts as rows',
            insightData: { result: [{ data: [0, 0], count: 0 }] },
            expected: true,
        },
        { name: 'nothing came back', insightData: { result: null }, expected: false },
        { name: 'no payload at all', insightData: undefined, expected: false },
    ])('hasResultRows: $name', ({ insightData, expected }) => {
        expect(hasResultRows(insightData)).toBe(expected)
    })
})
