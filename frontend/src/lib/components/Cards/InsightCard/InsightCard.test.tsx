import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { mockAllIsIntersecting } from 'react-intersection-observer/test-utils'

import { ApiError } from 'lib/api-error'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

import EXAMPLE_TRENDS from '~/mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType, DashboardPlacement, InsightModel } from '~/types'

import { InsightCard, shouldRenderInsightCardViz } from './InsightCard'

const tableQuery = { kind: NodeKind.DataTableNode } as InsightModel['query']
const autoSqlQuery = {
    kind: NodeKind.DataVisualizationNode,
    display: ChartDisplayType.Auto,
} as InsightModel['query']
const canvasQuery = {
    kind: NodeKind.DataVisualizationNode,
    display: ChartDisplayType.ActionsLineGraph,
} as InsightModel['query']

describe('InsightCard', () => {
    describe('failed tiles', () => {
        const insight = { ...EXAMPLE_TRENDS, result: null } as unknown as InsightModel

        beforeEach(() => {
            useMocks({})
            initKeaTests()
            jest.useFakeTimers()
        })

        afterEach(() => {
            cleanup()
            jest.useRealTimers()
        })

        it('shows a query failure while another attempt is queued', () => {
            render(
                <InsightCard
                    insight={insight}
                    placement="SavedInsightGrid"
                    doNotLoad
                    apiErrored
                    apiError={new ApiError('', 503)}
                    loadingQueued
                />
            )
            act(() => mockAllIsIntersecting(true))

            expect(screen.getByText("This query couldn't run right now")).toBeVisible()
        })

        it.each([
            { source: 'card', cardWait: 45, embeddedWait: null },
            { source: 'embedded query', cardWait: null, embeddedWait: 45 },
            { source: 'longer card wait', cardWait: 45, embeddedWait: 30 },
            { source: 'longer embedded wait', cardWait: 30, embeddedWait: 45 },
        ])('holds refresh controls until the $source cooldown ends', ({ cardWait, embeddedWait }) => {
            const refresh = jest.fn()
            const { container } = render(
                <InsightCard
                    insight={insight}
                    placement="SavedInsightGrid"
                    doNotLoad
                    apiErrored={cardWait !== null}
                    apiError={
                        cardWait === null
                            ? undefined
                            : new ApiError('', 503, new Headers({ 'Retry-After': String(cardWait) }))
                    }
                    refresh={refresh}
                />
            )
            act(() => mockAllIsIntersecting(true))
            if (embeddedWait !== null) {
                act(() => {
                    insightDataLogic({ dashboardItemId: insight.short_id }).actions.loadDataFailure(
                        'Capacity rejected',
                        new ApiError('', 503, new Headers({ 'Retry-After': String(embeddedWait) }))
                    )
                })
            }
            const headerRefresh = container.querySelector('[data-attr="insight-card-refresh"]')!
            expect(headerRefresh).toHaveAttribute('aria-disabled', 'true')
            fireEvent.click(headerRefresh)
            expect(refresh).not.toHaveBeenCalled()

            fireEvent.click(screen.getByLabelText('more'))
            const menuRefresh = screen.getByTestId('dashboard-tile-refresh-data')
            expect(menuRefresh).toHaveAttribute('aria-disabled', 'true')
            fireEvent.click(menuRefresh)
            expect(refresh).not.toHaveBeenCalled()

            act(() => jest.advanceTimersByTime(30_000))
            expect(headerRefresh).toHaveAttribute('aria-disabled', 'true')
            fireEvent.click(headerRefresh)
            expect(refresh).not.toHaveBeenCalled()
            act(() => jest.advanceTimersByTime(15_000))
            expect(headerRefresh).toHaveAttribute('aria-disabled', 'false')
            fireEvent.click(screen.getByLabelText('more'))
            expect(screen.getByTestId('dashboard-tile-refresh-data')).toHaveAttribute('aria-disabled', 'false')
            expect(refresh).not.toHaveBeenCalled()
            fireEvent.click(screen.getByTestId('dashboard-tile-refresh-data'))
            expect(refresh).toHaveBeenCalledTimes(1)
        })
    })

    it.each([
        {
            name: 'keeps a visible table mounted when the page is hidden',
            input: {
                isStorybook: false,
                placement: DashboardPlacement.Dashboard,
                inView: true,
                isPageVisible: false,
                query: tableQuery,
            },
            expected: true,
        },
        {
            name: 'keeps an auto SQL visualization mounted because it may render a table',
            input: {
                isStorybook: false,
                placement: DashboardPlacement.Dashboard,
                inView: true,
                isPageVisible: false,
                query: autoSqlQuery,
            },
            expected: true,
        },
        {
            name: 'unmounts a visible canvas chart when the page is hidden',
            input: {
                isStorybook: false,
                placement: DashboardPlacement.Dashboard,
                inView: true,
                isPageVisible: false,
                query: canvasQuery,
            },
            expected: false,
        },
        {
            name: 'unmounts an offscreen table',
            input: {
                isStorybook: false,
                placement: DashboardPlacement.Dashboard,
                inView: false,
                isPageVisible: true,
                query: tableQuery,
            },
            expected: false,
        },
        {
            name: 'renders a visible canvas chart on a visible page',
            input: {
                isStorybook: false,
                placement: DashboardPlacement.Dashboard,
                inView: true,
                isPageVisible: true,
                query: canvasQuery,
            },
            expected: true,
        },
        {
            name: 'renders exports regardless of visibility',
            input: {
                isStorybook: false,
                placement: DashboardPlacement.Export,
                inView: false,
                isPageVisible: false,
                query: canvasQuery,
            },
            expected: true,
        },
    ])('$name', ({ input, expected }) => {
        expect(shouldRenderInsightCardViz(input)).toBe(expected)
    })
})
