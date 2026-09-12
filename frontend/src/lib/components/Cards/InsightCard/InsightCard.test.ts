import { act, renderHook } from '@testing-library/react'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, DashboardPlacement, QueryBasedInsightModel } from '~/types'

import { shouldRenderInsightCardViz, shouldStaggerVizMount, useStaggeredVizMount } from './InsightCard'
import { requestInsightVizMount } from './insightVizMountScheduler'

jest.mock('./insightVizMountScheduler', () => ({
    requestInsightVizMount: jest.fn(),
    setDashboardDragActive: jest.fn(),
}))

const mockRequestInsightVizMount = requestInsightVizMount as jest.Mock

const tableQuery = { kind: NodeKind.DataTableNode } as QueryBasedInsightModel['query']
const autoSqlQuery = {
    kind: NodeKind.DataVisualizationNode,
    display: ChartDisplayType.Auto,
} as QueryBasedInsightModel['query']
const canvasQuery = {
    kind: NodeKind.DataVisualizationNode,
    display: ChartDisplayType.ActionsLineGraph,
} as QueryBasedInsightModel['query']

describe('InsightCard', () => {
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
            name: 'keeps an offscreen table mounted so it does not blank and rebuild on scroll',
            input: {
                isStorybook: false,
                placement: DashboardPlacement.Dashboard,
                inView: false,
                isPageVisible: true,
                query: tableQuery,
            },
            expected: true,
        },
        {
            name: 'unmounts an offscreen canvas chart to release its backing store',
            input: {
                isStorybook: false,
                placement: DashboardPlacement.Dashboard,
                inView: false,
                isPageVisible: true,
                query: canvasQuery,
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

    it.each([
        {
            name: 'staggers a canvas chart on an interactive dashboard',
            input: { isStorybook: false, placement: DashboardPlacement.Dashboard, rendersToCanvas: true },
            expected: true,
        },
        {
            name: 'does not stagger a non-canvas viz',
            input: { isStorybook: false, placement: DashboardPlacement.Dashboard, rendersToCanvas: false },
            expected: false,
        },
        {
            name: 'does not stagger during image export so every canvas tile mounts before capture',
            input: { isStorybook: false, placement: DashboardPlacement.Export, rendersToCanvas: true },
            expected: false,
        },
        {
            name: 'does not stagger in storybook',
            input: { isStorybook: true, placement: DashboardPlacement.Dashboard, rendersToCanvas: true },
            expected: false,
        },
    ])('$name', ({ input, expected }) => {
        expect(shouldStaggerVizMount(input)).toBe(expected)
    })

    describe('useStaggeredVizMount', () => {
        let release: (() => void) | undefined
        const cancel = jest.fn()

        beforeEach(() => {
            release = undefined
            cancel.mockClear()
            mockRequestInsightVizMount.mockReset()
            mockRequestInsightVizMount.mockImplementation((request: () => void) => {
                release = request
                return cancel
            })
        })

        it('waits for a fresh scheduler slot when a canvas tile re-enters the viewport', () => {
            const renders: boolean[] = []
            const { rerender } = renderHook(
                ({ eligible }) => {
                    const shown = useStaggeredVizMount(eligible, true)
                    renders.push(shown)
                    return shown
                },
                { initialProps: { eligible: true } }
            )

            // Nothing mounts until the scheduler releases a slot.
            expect(renders.at(-1)).toBe(false)
            act(() => release?.())
            expect(renders.at(-1)).toBe(true)

            // The tile scrolls offscreen and its viz unmounts.
            rerender({ eligible: false })
            expect(renders.at(-1)).toBe(false)

            // Back in view it must not mount from stale readiness — it waits for a new slot.
            const reentry = renders.length
            rerender({ eligible: true })
            expect(renders.slice(reentry).some(Boolean)).toBe(false)

            act(() => release?.())
            expect(renders.at(-1)).toBe(true)
        })
    })
})
