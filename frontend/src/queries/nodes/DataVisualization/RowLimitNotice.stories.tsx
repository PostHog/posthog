import { Meta, StoryObj } from '@storybook/react'

import { DataTableVisualization } from '~/queries/nodes/DataVisualization/DataVisualization'
import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

const query: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: 'SELECT country, visitors FROM web_stats ORDER BY visitors DESC',
    },
    display: ChartDisplayType.ActionsTable,
}

function buildResponse(rowCount: number, hasMore: boolean): HogQLQueryResponse<string[][]> {
    return {
        results: Array.from({ length: rowCount }, (_, index) => [`Country ${index + 1}`, String(1000 - index)]),
        columns: ['country', 'visitors'],
        types: [
            ['country', 'String'],
            ['visitors', 'UInt64'],
        ],
        hasMore,
        limit: 100,
    }
}

const meta: Meta<typeof DataTableVisualization> = {
    title: 'Queries/RowLimitNotice',
    component: DataTableVisualization,
    // A dashboard tile is about this tall, so the notice has to stay in view over a scrolling table.
    decorators: [
        (Story) => (
            <div className="InsightCard border rounded w-[640px] h-[320px] flex flex-col">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof DataTableVisualization>

export const Truncated: Story = {
    render: () => (
        <DataTableVisualization
            uniqueKey="row-limit-truncated"
            query={query}
            setQuery={() => {}}
            cachedResults={buildResponse(100, true)}
            readOnly
            embedded
        />
    ),
}

export const NotTruncated: Story = {
    render: () => (
        <DataTableVisualization
            uniqueKey="row-limit-not-truncated"
            query={query}
            setQuery={() => {}}
            cachedResults={buildResponse(12, false)}
            readOnly
            embedded
        />
    ),
}
