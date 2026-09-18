import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, DashboardPlacement, QueryBasedInsightModel } from '~/types'

import { shouldRenderInsightCardViz, useActualVisibilityChange } from './InsightCard'

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
    it('waits for a real zero-margin observation and reports observed-offscreen separately from unobserved', () => {
        const onChange = jest.fn()
        const observedEntry = {} as IntersectionObserverEntry
        const unobserved = renderHook(({ entry, inView }) => useActualVisibilityChange(entry, inView, onChange), {
            initialProps: { entry: undefined as IntersectionObserverEntry | undefined, inView: false },
        })

        unobserved.unmount()
        expect(onChange).not.toHaveBeenCalled()

        const { rerender, unmount } = renderHook(
            ({ entry, inView }) => useActualVisibilityChange(entry, inView, onChange),
            { initialProps: { entry: undefined as IntersectionObserverEntry | undefined, inView: false } }
        )

        expect(onChange).not.toHaveBeenCalled()
        rerender({ entry: observedEntry, inView: false })
        expect(onChange).toHaveBeenLastCalledWith(false)
        rerender({ entry: observedEntry, inView: true })
        expect(onChange).toHaveBeenLastCalledWith(true)
        unmount()
        expect(onChange).toHaveBeenLastCalledWith(false)
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
import { renderHook } from '@testing-library/react'
