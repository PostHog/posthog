import { Meta, StoryObj } from '@storybook/react'

import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { ChartDisplayType } from '~/types'

import { DEFAULT_BI_CONFIG } from './biEditorTypes'
import { BIPivotTable } from './BIPivotTable'

const field = (name: string): BIField => ({
    id: name,
    name,
    expression: name,
    type: 'string',
    source: { table: 'events' },
})
const config: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: { table: 'events' },
    chartType: ChartDisplayType.TwoDimensionalHeatmap,
    rows: [field('Region'), field('City')],
    columns: [field('Year'), field('Quarter')],
    values: [
        {
            field: field('revenue'),
            aggregation: 'sum',
            formatting: { style: 'number', prefix: '€', decimalPlaces: 0 },
            display: { label: 'Revenue' },
        },
        {
            field: field('user'),
            aggregation: 'count_distinct',
            display: { label: 'Customers' },
            formatting: { style: 'number', decimalPlaces: 0 },
        },
    ],
    totals: { rows: true, columns: true, subtotals: true },
}
const detail: [string, string, string, number, number][] = [
    ['Europe', 'Paris', 'Q1', 1200, 18],
    ['Europe', 'Paris', 'Q2', 1500, 23],
    ['Europe', 'Rome', 'Q1', 800, 12],
    ['Europe', 'Rome', 'Q2', 950, 14],
    ['Americas', 'Boston', 'Q1', 2100, 31],
    ['Americas', 'Boston', 'Q2', 2400, 34],
]
const results = [
    ['Europe', 'Paris'],
    ['Europe', 'Rome'],
    ['Europe', 'Total'],
    ['Americas', 'Boston'],
    ['Americas', 'Total'],
    ['Total', 'Total'],
].flatMap((row) =>
    [
        ['2026', 'Q1'],
        ['2026', 'Q2'],
        ['2026', 'Total'],
        ['Total', 'Total'],
    ].map((column) => {
        const matching = detail.filter(
            ([region, city, quarter]) =>
                (row[0] === 'Total' || region === row[0]) &&
                (row[1] === 'Total' || city === row[1]) &&
                (column[1] === 'Total' || quarter === column[1])
        )
        return [
            JSON.stringify(row),
            JSON.stringify(column),
            matching.reduce((sum, item) => sum + item[3], 0),
            matching.reduce((sum, item) => sum + item[4], 0),
        ]
    })
)

const meta: Meta<typeof BIPivotTable> = {
    title: 'Products/Business intelligence/Pivot table',
    component: BIPivotTable,
    parameters: { layout: 'fullscreen' },
    args: { config, columns: ['bi_rows', 'bi_columns', 'sum_revenue', 'count_distinct_user_2'], results },
    decorators: [
        (Story) => (
            <div className="w-full max-w-5xl">
                <Story />
            </div>
        ),
    ],
}
export default meta
export const MultipleMeasuresAndHierarchies: StoryObj<typeof BIPivotTable> = {}
