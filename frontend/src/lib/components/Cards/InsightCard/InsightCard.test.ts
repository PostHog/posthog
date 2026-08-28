import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, DashboardPlacement, QueryBasedInsightModel } from '~/types'

import { shouldRenderInsightCardViz, shouldStaggerVizMount } from './InsightCard'

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
})
