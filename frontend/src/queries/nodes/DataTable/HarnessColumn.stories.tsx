import type { Meta, StoryObj } from '@storybook/react'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataTableNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'

const query: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: 'SELECT properties.$virt_mcp_harness AS client, count() AS calls FROM events GROUP BY client',
    },
}

const cachedResults: HogQLQueryResponse = {
    columns: ['client', 'calls'],
    column_formats: ['mcp_harness', null],
    types: ['String', 'UInt64'],
    results: [
        ['Claude Code', 12],
        ['OpenAI Codex', 7],
        ['Other', 2],
    ],
}

const meta: Meta<typeof DataTable> = {
    title: 'Queries/DataTable/HarnessColumn',
    component: DataTable,
    parameters: {
        testOptions: { waitForSelector: '.DataTable [data-attr="hogqlx-brand-mark-label"]' },
    },
}

export default meta

export const ArbitraryQueryResult: StoryObj<typeof DataTable> = {
    tags: ['harness-result-visual'],
    render: () => (
        <div className="p-4">
            <DataTable query={query} setQuery={() => {}} cachedResults={cachedResults} readOnly />
        </div>
    ),
}
