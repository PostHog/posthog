import { Meta, StoryObj } from '@storybook/react'

import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { ChartDisplayType } from '~/types'

import { BIComparisonSummary } from './BIComparisonSummary'
import { DEFAULT_BI_CONFIG } from './biEditorTypes'

const field: BIField = {
    id: 'revenue',
    name: 'revenue',
    expression: 'revenue',
    type: 'float',
    source: { table: 'events' },
}
const config: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: field.source,
    chartType: ChartDisplayType.BoldNumber,
    dateRange: { date_from: '-7d' },
    compareFilter: { compare: true },
    values: [
        {
            field,
            aggregation: 'sum',
            display: { label: 'Revenue' },
            formatting: { style: 'number', prefix: '€', decimalPlaces: 2 },
        },
    ],
}
const meta: Meta<typeof BIComparisonSummary> = {
    title: 'Products/Business intelligence/Comparison summary',
    component: BIComparisonSummary,
    parameters: { layout: 'fullscreen' },
    decorators: [
        (Story) => (
            <div className="w-full max-w-5xl">
                <Story />
            </div>
        ),
    ],
}
export default meta
export const KPI: StoryObj<typeof BIComparisonSummary> = {
    args: {
        config,
        card: true,
        columns: ['sum_revenue', 'bi_comparison'],
        results: [
            [12500, 'Current period'],
            [10000, 'Previous period'],
        ],
    },
}
export const Table: StoryObj<typeof BIComparisonSummary> = {
    args: {
        config: {
            ...config,
            chartType: ChartDisplayType.ActionsTable,
            rows: [{ ...field, id: 'event', expression: 'event', name: 'Event', type: 'string' }],
        },
        columns: ['bi_row_event', 'sum_revenue', 'bi_comparison'],
        results: [
            ['Purchase', 12500, 'Current period'],
            ['Purchase', 10000, 'Previous period'],
            ['New subscription', 500, 'Current period'],
            ['New subscription', 0, 'Previous period'],
            ['Refund', -100, 'Current period'],
            ['Refund', -200, 'Previous period'],
        ],
    },
}
