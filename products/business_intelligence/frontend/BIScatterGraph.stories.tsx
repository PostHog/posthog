import { Meta, StoryObj } from '@storybook/react'

import { DataTableVisualization } from '~/queries/nodes/DataVisualization/DataVisualization'
import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { buildBIQuery, getBIResultDimensions, getBIResultMeasureColumns } from './biEditorTypes'

const field = (name: string, type: BIField['type'] = 'string'): BIField => ({
    id: name,
    name,
    expression: name,
    type,
    source: { table: 'example_orders' },
})
const config: BIConfig = {
    source: { table: 'example_orders' },
    chartType: ChartDisplayType.ScatterPlot,
    limit: 1000,
    rows: [field('item'), field('region')],
    columns: [],
    filters: [],
    values: [
        { field: field('revenue', 'float'), aggregation: 'sum' },
        { field: field('cost', 'float'), aggregation: 'sum' },
    ],
    colorBy: 'region',
    memberAliases: [
        {
            field: field('region'),
            aliases: [
                { value: 'east', label: 'East region' },
                { value: 'west', label: 'West region' },
            ],
        },
    ],
}
const columns = [
    ...getBIResultDimensions(config).map(({ column }) => column),
    ...getBIResultMeasureColumns(config).map(({ column }) => column),
]
const results = Array.from({ length: 30 }, (_, index) => [
    `Item ${index + 1}`,
    index % 2 ? 'east' : 'west',
    100 + (index % 9) * 40,
    20 + ((index * 7) % 23) * 6,
])
const meta: Meta = {
    title: 'Products/Business intelligence/Scatter',
    parameters: { layout: 'centered', testOptions: { snapshotBrowsers: ['chromium'] } },
}
export default meta

const render = (width: number, editing: boolean): JSX.Element => (
    <div className="flex h-[34rem] flex-col" style={{ width }}>
        <DataTableVisualization
            query={{ ...buildBIQuery(config)!.node, kind: NodeKind.BIVisualizationNode, config }}
            setQuery={() => {}}
            cachedResults={{
                columns,
                types: columns.map((column, index) => [column, index < 2 ? 'String' : 'Float64']),
                results,
            }}
            context={{
                insightProps: { dashboardItemId: 'new-SQL-bi-scatter' },
                ...(editing ? { onKeepBISelection: () => {} } : {}),
            }}
            editMode={editing}
            readOnly={!editing}
        />
    </div>
)

export const DetailAndColor: StoryObj = { render: () => render(960, true) }
export const Narrow: StoryObj = { render: () => render(520, true) }
export const ReadOnly: StoryObj = { render: () => render(960, false) }
