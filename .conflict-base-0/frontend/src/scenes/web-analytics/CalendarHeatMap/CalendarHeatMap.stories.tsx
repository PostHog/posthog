import { Meta, StoryObj } from '@storybook/react'

import { CalendarHeatMap } from './CalendarHeatMap'

const meta: Meta<typeof CalendarHeatMap> = {
    title: 'Scenes/Web Analytics/CalendarHeatMap',
    component: CalendarHeatMap,
    parameters: {
        layout: 'fullscreen',
    },
}
export default meta
type Story = StoryObj<typeof CalendarHeatMap>

const mockTooltips = {
    getDataTooltip: (row: string, col: string, value: number) => `${row} - ${col}: ${value}`,
    getColumnAggregationTooltip: (label: string, col: string, value: number) => `${label} - ${col}: ${value}`,
    getRowAggregationTooltip: (label: string, row: string, value: number) => `${label} - ${row}: ${value}`,
    getOverallAggregationTooltip: (label: string, value: number) => `${label}: ${value}`,
}

const mockData = {
    isLoading: false,
    rowLabels: ['Homepage', 'Pricing', 'Docs', 'Blog'],
    columnLabels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
    allAggregationsLabel: 'Total',
    processedData: {
        matrix: [
            [1200, 1500, 1800, 1400, 1600],
            [800, 950, 1100, 900, 1000],
            [600, 750, 900, 700, 800],
            [400, 550, 700, 500, 600],
        ],
        columnsAggregations: [3000, 3750, 4500, 3500, 4000],
        rowsAggregations: [7500, 4750, 3750, 2750],
        overallValue: 18750,
        maxOverall: 1800,
        minOverall: 400,
        maxRowAggregation: 7500,
        minRowAggregation: 2750,
        maxColumnAggregation: 4500,
        minColumnAggregation: 3000,
    },
    ...mockTooltips,
}

export const Loading: Story = {
    args: {
        isLoading: true,
        rowLabels: [],
        columnLabels: [],
        allAggregationsLabel: 'Total',
        processedData: {
            matrix: [],
            columnsAggregations: [],
            rowsAggregations: [],
            overallValue: 0,
            maxOverall: 0,
            minOverall: 0,
            maxRowAggregation: 0,
            minRowAggregation: 0,
            maxColumnAggregation: 0,
            minColumnAggregation: 0,
        },
        ...mockTooltips,
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const NoResults: Story = {
    args: {
        isLoading: false,
        rowLabels: ['Page A', 'Page B', 'Page C'],
        columnLabels: ['Mon', 'Tue', 'Wed'],
        allAggregationsLabel: 'Total',
        processedData: {
            matrix: [
                [0, 0, 0],
                [0, 0, 0],
                [0, 0, 0],
            ],
            columnsAggregations: [0, 0, 0],
            rowsAggregations: [0, 0, 0],
            overallValue: 0,
            maxOverall: 0,
            minOverall: 0,
            maxRowAggregation: 0,
            minRowAggregation: 0,
            maxColumnAggregation: 0,
            minColumnAggregation: 0,
        },
        ...mockTooltips,
    },
}

export const WithData: Story = {
    args: mockData,
}

export const WithHiddenColumnAggregation: Story = {
    args: {
        ...mockData,
        showColumnAggregations: false,
    },
}

export const WithHiddenRowAggregation: Story = {
    args: {
        ...mockData,
        showRowAggregations: false,
    },
}

export const WithAllHiddenAggregation: Story = {
    args: {
        ...mockData,
        showColumnAggregations: false,
        showRowAggregations: false,
    },
}
