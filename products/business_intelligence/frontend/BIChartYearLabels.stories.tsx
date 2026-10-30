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
    limit: 50_000,
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

function ChartYears({ dates: chartDates, width = '48rem' }: { dates: string[]; width?: string }): JSX.Element {
    return (
        <div className="flex h-96 flex-col" style={{ width }}>
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
                    results: chartDates.map((date, index) => [date, 100 + (index % 4) * 50]),
                }}
                context={{ insightProps: { dashboardItemId: 'new-SQL-bi-years' } }}
                readOnly
            />
        </div>
    )
}

export const PartialYears: StoryObj = { render: () => <ChartYears dates={dates} /> }

export const ManyYearsNarrow: StoryObj = {
    render: () => (
        <ChartYears
            dates={Array.from(
                { length: 360 },
                (_, i) => `${2000 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}-01`
            )}
            width="520px"
        />
    ),
}
