import { Meta, StoryObj } from '@storybook/react'

import { DataTableVisualization } from '~/queries/nodes/DataVisualization/DataVisualization'
import { BIConfig } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { buildBIQuery } from './biEditorTypes'

const config: BIConfig = {
    source: { table: 'events' },
    rows: [
        {
            id: 'timestamp',
            name: 'timestamp',
            expression: 'timestamp',
            type: 'datetime',
            source: { table: 'events' },
            dateBucket: 'month',
        },
    ],
    columns: [],
    values: [
        {
            field: {
                id: 'revenue',
                name: 'revenue',
                expression: 'revenue',
                type: 'float',
                source: { table: 'events' },
            },
            aggregation: 'sum',
        },
    ],
    filters: [],
    chartType: ChartDisplayType.ActionsBar,
    limit: 100,
}
const dates = [
    '2025-10-01',
    '2025-11-01',
    '2025-12-01',
    '2026-01-01',
    '2026-02-01',
    '2026-03-01',
    '2026-04-01',
    '2026-05-01',
    '2026-06-01',
    '2026-07-01',
    '2026-08-01',
    '2026-09-01',
]
const meta: Meta = {
    title: 'Products/Business intelligence/Chart years',
    parameters: { layout: 'centered', mockDate: '2026-10-01' },
}
export default meta

export const PartialYears: StoryObj = {
    render: () => (
        <div className="flex h-96 w-[48rem] flex-col">
            <DataTableVisualization
                query={{
                    ...buildBIQuery(config)!.node,
                    kind: NodeKind.BIVisualizationNode,
                    config,
                    chartSettings: {
                        xAxis: { column: 'toStartOfMonth(timestamp)' },
                        yAxis: [{ column: 'sum_revenue' }],
                    },
                }}
                setQuery={() => {}}
                cachedResults={{
                    columns: ['toStartOfMonth(timestamp)', 'sum_revenue'],
                    types: [
                        ['toStartOfMonth(timestamp)', 'DateTime'],
                        ['sum_revenue', 'Float64'],
                    ],
                    results: dates.map((date, index) => [date, 100 + (index % 4) * 50]),
                }}
                context={{ insightProps: { dashboardItemId: 'new-SQL-bi-years' } }}
                readOnly
            />
        </div>
    ),
}
