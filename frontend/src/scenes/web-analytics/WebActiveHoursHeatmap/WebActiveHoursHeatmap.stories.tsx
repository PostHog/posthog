import { Meta, StoryObj } from '@storybook/react'

import { NodeKind } from '~/queries/schema/schema-general'
import { CalendarHeatmapQuery } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { BaseMathType } from '~/types'

import { WebActiveHoursHeatmap } from './WebActiveHoursHeatmap'
const meta: Meta<typeof WebActiveHoursHeatmap> = {
    title: 'Scenes/Web Analytics/WebActiveHoursHeatmap',
    component: WebActiveHoursHeatmap,
    parameters: {
        layout: 'fullscreen',
    },
}
export default meta
type Story = StoryObj<typeof WebActiveHoursHeatmap>

const theQuery: CalendarHeatmapQuery = {
    kind: NodeKind.CalendarHeatmapQuery,
    series: [
        {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            name: '$pageview',
            math: BaseMathType.UniqueUsers,
        },
    ],
    dateRange: {
        date_from: '-7d',
        date_to: 'now',
    },
    properties: [],
}

const mockContext: QueryContext = {
    insightProps: {
        dashboardItemId: undefined,
    },
}

const mockData = {
    data: [
        { row: 1, column: 9, value: 150 }, // Monday 9am
        { row: 1, column: 10, value: 200 }, // Monday 10am
        { row: 2, column: 14, value: 180 }, // Tuesday 2pm
        { row: 3, column: 16, value: 220 }, // Wednesday 4pm
    ],
    columnAggregations: [
        { column: 9, value: 150 },
        { column: 10, value: 200 },
        { column: 14, value: 180 },
        { column: 16, value: 220 },
    ],
    rowAggregations: [
        { row: 1, value: 350 }, // Monday total
        { row: 2, value: 180 }, // Tuesday total
        { row: 3, value: 220 }, // Wednesday total
    ],
    allAggregations: 750,
}

export const WithData: Story = {
    args: {
        query: theQuery,
        context: mockContext,
        cachedResults: { results: mockData },
    },
}

export const NoData: Story = {
    args: {
        query: theQuery,
        context: mockContext,
        cachedResults: { results: { data: [], columnAggregations: [], rowAggregations: [], allAggregations: 0 } },
    },
}
