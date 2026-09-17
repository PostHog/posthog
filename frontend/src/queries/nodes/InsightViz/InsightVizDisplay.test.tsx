import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { InsightType } from '~/types'

import { InsightVizDisplay, shouldShowDashboardInsightRefreshHint } from './InsightVizDisplay'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

jest.mock('products/product_analytics/frontend/insights/retention/RetentionContainer', () => ({
    RetentionContainer: () => <div data-attr="retention-container" />,
}))

jest.mock('./ResultCustomizationsModal', () => ({ ResultCustomizationsModal: () => null }))

const ALL_INSIGHT_TYPES = Object.values(InsightType) as InsightType[]
/** Insight types that use the dashboard refresh hint (excludes web analytics — separate UX). */
const DASHBOARD_HINT_INSIGHT_TYPES = ALL_INSIGHT_TYPES.filter((t) => t !== InsightType.WEB_ANALYTICS)

describe('InsightVizDisplay', () => {
    it('reports an empty retention result only after that exact response reference is committed', () => {
        const expectedEmptyRetention: unknown[] = []
        let insightData = { result: [] as unknown[] }
        const onCommitted = jest.fn()

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
                return { activeView: InsightType.RETENTION }
            }
            if (logic.pathString?.includes('funnelDataLogic')) {
                return {
                    funnelVizType: null,
                    hasFunnelResults: false,
                    isFunnelWithEnoughSteps: true,
                    isFunnelWithIncompleteDataWarehouseStep: false,
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
                    insightData,
                    validationError: null,
                    validationErrorCode: null,
                    theme: {},
                }
            }
            return {}
        })

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

    it('does not report an exact result while an invalid funnel configuration branch is rendered', () => {
        const expectedResult = [{ count: 1 }]
        const onCommitted = jest.fn()

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
                return { activeView: InsightType.FUNNELS }
            }
            if (logic.pathString?.includes('funnelDataLogic')) {
                return {
                    funnelVizType: null,
                    hasFunnelResults: true,
                    isFunnelWithEnoughSteps: false,
                    isFunnelWithIncompleteDataWarehouseStep: false,
                }
            }
            if (logic.pathString?.includes('insightVizDataLogic')) {
                return {
                    isFunnels: true,
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
                    query: { kind: 'InsightVizNode', source: { kind: 'FunnelsQuery', series: [{}] } },
                    querySource: { kind: 'FunnelsQuery', series: [{}] },
                    display: null,
                    series: [{}],
                    insightData: { result: expectedResult },
                    validationError: null,
                    validationErrorCode: null,
                    theme: {},
                }
            }
            return {}
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
    })

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
})
