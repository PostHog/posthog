import { ChartDisplayType, InsightType } from '~/types'

import { hasNoVisibleTrendsData, isChartBasedDisplay, shouldShowDashboardInsightRefreshHint } from './InsightVizDisplay'

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
        { name: 'undefined display falls back to default line graph', display: undefined, expected: true },
        { name: 'null display falls back to default line graph', display: null, expected: true },
        { name: 'line graph is chart-based', display: ChartDisplayType.ActionsLineGraph, expected: true },
        {
            name: 'cumulative line is chart-based',
            display: ChartDisplayType.ActionsLineGraphCumulative,
            expected: true,
        },
        { name: 'bar is chart-based', display: ChartDisplayType.ActionsBar, expected: true },
        { name: 'unstacked bar is chart-based', display: ChartDisplayType.ActionsUnstackedBar, expected: true },
        { name: 'stacked bar is chart-based', display: ChartDisplayType.ActionsStackedBar, expected: true },
        { name: 'area graph is chart-based', display: ChartDisplayType.ActionsAreaGraph, expected: true },
        { name: 'bold number renders zero clearly', display: ChartDisplayType.BoldNumber, expected: false },
        { name: 'pie renders empty state itself', display: ChartDisplayType.ActionsPie, expected: false },
        { name: 'table renders zero rows clearly', display: ChartDisplayType.ActionsTable, expected: false },
        { name: 'world map handles its own emptiness', display: ChartDisplayType.WorldMap, expected: false },
        {
            name: 'horizontal bar renders zero rows clearly',
            display: ChartDisplayType.ActionsBarValue,
            expected: false,
        },
    ])('isChartBasedDisplay: $name', ({ display, expected }) => {
        expect(isChartBasedDisplay(display)).toBe(expected)
    })

    it.each([
        { name: 'null result (still loading or cache miss)', result: null, expected: false },
        { name: 'undefined result', result: undefined, expected: false },
        { name: 'non-array result (defensive)', result: 'oops' as unknown, expected: false },
        { name: 'empty result array — every series filtered out', result: [], expected: true },
        {
            name: 'all series have all-zero data points (e.g. filterTestAccounts removed everything)',
            result: [
                { data: [0, 0, 0], count: 0, aggregated_value: 0 },
                { data: [0, 0, 0], count: 0, aggregated_value: 0 },
            ],
            expected: true,
        },
        {
            name: 'series has at least one non-zero data point',
            result: [{ data: [0, 0, 5, 0], count: 5, aggregated_value: 5 }],
            expected: false,
        },
        {
            name: 'series has non-zero aggregated_value even with empty data array',
            result: [{ data: [], count: 0, aggregated_value: 42 }],
            expected: false,
        },
        {
            name: 'series has non-zero count (e.g. lifecycle row)',
            result: [{ data: [0, 0, 0], count: 7, aggregated_value: 0 }],
            expected: false,
        },
        {
            name: 'mix: one all-zero, one non-zero — still has visible data',
            result: [
                { data: [0, 0, 0], count: 0, aggregated_value: 0 },
                { data: [1, 2, 3], count: 6, aggregated_value: 6 },
            ],
            expected: false,
        },
        {
            name: 'data array contains nulls — treated as zero',
            result: [{ data: [null, null, null], count: 0, aggregated_value: 0 }],
            expected: true,
        },
    ])('hasNoVisibleTrendsData: $name', ({ result, expected }) => {
        expect(hasNoVisibleTrendsData(result)).toBe(expected)
    })
})
