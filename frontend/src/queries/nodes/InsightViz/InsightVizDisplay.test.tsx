import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { InsightType } from '~/types'

import {
    InsightVizDisplay,
    hasResultRows,
    shouldShowAIAnalysisSection,
    shouldShowDashboardInsightRefreshHint,
} from './InsightVizDisplay'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

jest.mock('products/product_analytics/frontend/insights/retention/RetentionContainer', () => ({
    RetentionContainer: () => <div data-attr="retention-container" />,
}))

jest.mock('scenes/insights/EmptyStates', () => ({
    ...jest.requireActual('scenes/insights/EmptyStates'),
    InsightEmptyState: () => <div data-attr="insight-empty-state" />,
}))

jest.mock('./ResultCustomizationsModal', () => ({ ResultCustomizationsModal: () => null }))

const ALL_INSIGHT_TYPES = Object.values(InsightType) as InsightType[]
/** Insight types that use the dashboard refresh hint (excludes web analytics — separate UX). */
const DASHBOARD_HINT_INSIGHT_TYPES = ALL_INSIGHT_TYPES.filter((t) => t !== InsightType.WEB_ANALYTICS)

function mockReadinessValues(
    getInsightData: () => { result: unknown },
    overrides: {
        activeView?: InsightType
        funnelData?: Record<string, unknown>
        insightVizData?: Record<string, unknown>
    } = {}
): void {
    ;(useActions as jest.Mock).mockReturnValue({ loadData: jest.fn(), updateQuerySource: jest.fn() })
    ;(useValues as jest.Mock).mockImplementation((logic) => {
        if (logic === insightLogic) {
            return {
                insightProps: { dashboardItemId: undefined },
                canEditInsight: false,
                isInDashboardContext: true,
            }
        }
        if (logic === insightDataLogic) {
            return { exportContext: null, queryId: null }
        }
        if (logic.pathString?.includes('insightNavLogic')) {
            return { activeView: overrides.activeView ?? InsightType.RETENTION }
        }
        if (logic.pathString?.includes('funnelDataLogic')) {
            return {
                funnelVizType: null,
                hasFunnelResults: false,
                isFunnelWithEnoughSteps: true,
                isFunnelWithIncompleteDataWarehouseStep: false,
                ...overrides.funnelData,
            }
        }
        if (logic.pathString?.includes('insightVizDataLogic')) {
            return {
                isFunnels: false,
                isPaths: false,
                hasDetailedResultsTable: false,
                showLegend: false,
                usesInChartLegend: false,
                hasFormula: false,
                supportsDisplay: true,
                samplingFactor: null,
                insightDataLoading: false,
                hasRenderableResults: true,
                erroredQueryId: null,
                timedOutQueryId: null,
                vizSpecificOptions: {},
                query: { kind: 'InsightVizNode', source: { kind: 'RetentionQuery' } },
                querySource: { kind: 'RetentionQuery' },
                display: null,
                series: [],
                insightData: getInsightData(),
                validationError: null,
                validationErrorCode: null,
                theme: {},
                ...overrides.insightVizData,
            }
        }
        return {}
    })
}

describe('InsightVizDisplay', () => {
    it('reports an empty retention result only after that exact response reference is committed', () => {
        const expectedEmptyRetention: unknown[] = []
        let insightData = { result: [] as unknown[] }
        const onCommitted = jest.fn()

        mockReadinessValues(() => insightData)

        const context = {
            dashboardJourneyRenderReadiness: {
                attemptId: 'attempt-1',
                tileId: 7,
                insightShortId: 'retention',
                insightType: 'RETENTION' as const,
                expectedResult: expectedEmptyRetention,
            },
            onDashboardJourneyRenderCommitted: onCommitted,
        }
        const view = render(
            <InsightVizDisplay
                embedded
                showingResults
                disableHeader
                disableTable
                disableCorrelationTable
                context={context}
            />
        )

        expect(screen.getByTestId('retention-container')).toBeInTheDocument()
        expect(onCommitted).not.toHaveBeenCalled()

        insightData = { result: expectedEmptyRetention }
        view.rerender(
            <InsightVizDisplay
                embedded
                showingResults
                disableHeader
                disableTable
                disableCorrelationTable
                context={context}
            />
        )
        expect(onCommitted).toHaveBeenCalledWith('attempt-1', 7)
        expect(onCommitted).toHaveBeenCalledTimes(1)
    })

    it.each([
        { name: 'showingResults is absent', showingResultsProps: {} },
        { name: 'showingResults is false', showingResultsProps: { showingResults: false } },
    ])('does not report an exact result when $name', ({ showingResultsProps }) => {
        const expectedResult: unknown[] = []
        const onCommitted = jest.fn()

        mockReadinessValues(() => ({ result: expectedResult }))

        render(
            <InsightVizDisplay
                embedded
                disableHeader
                disableTable
                disableCorrelationTable
                context={{
                    dashboardJourneyRenderReadiness: {
                        attemptId: 'attempt-hidden',
                        tileId: 8,
                        insightShortId: 'hidden-retention',
                        insightType: 'RETENTION',
                        expectedResult,
                    },
                    onDashboardJourneyRenderCommitted: onCommitted,
                }}
                {...showingResultsProps}
            />
        )

        expect(onCommitted).not.toHaveBeenCalled()
    })

    it.each([
        {
            name: 'invalid funnel configuration',
            expectedResult: [{ count: 1 }],
            hasFunnelResults: true,
            isFunnelWithEnoughSteps: false,
        },
        {
            name: 'funnel with no results',
            expectedResult: [],
            hasFunnelResults: false,
            isFunnelWithEnoughSteps: true,
        },
    ])(
        'does not report an exact result while the $name blocking branch is rendered',
        ({ expectedResult, hasFunnelResults, isFunnelWithEnoughSteps }) => {
            const onCommitted = jest.fn()

            mockReadinessValues(() => ({ result: expectedResult }), {
                activeView: InsightType.FUNNELS,
                funnelData: { hasFunnelResults, isFunnelWithEnoughSteps },
                insightVizData: {
                    isFunnels: true,
                    query: { kind: 'InsightVizNode', source: { kind: 'FunnelsQuery', series: [{}] } },
                    querySource: { kind: 'FunnelsQuery', series: [{}] },
                    series: [{}],
                },
            })

            render(
                <InsightVizDisplay
                    embedded
                    showingResults
                    disableHeader
                    disableTable
                    disableCorrelationTable
                    context={{
                        dashboardJourneyRenderReadiness: {
                            attemptId: 'attempt-invalid',
                            tileId: 8,
                            insightShortId: 'invalid-funnel',
                            insightType: 'FUNNELS',
                            expectedResult,
                        },
                        onDashboardJourneyRenderCommitted: onCommitted,
                    }}
                />
            )

            expect(onCommitted).not.toHaveBeenCalled()
        }
    )

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
