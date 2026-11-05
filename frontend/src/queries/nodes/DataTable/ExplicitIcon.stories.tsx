import type { Meta, StoryObj } from '@storybook/react'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { IMAGE_QUERY, IMAGE_RESULTS } from '~/queries/nodes/HogQLX/image.fixtures'
import { DataTableNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'

const query: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: "SELECT withIcon('Claude Code', 'Claude') AS client, 12 AS calls UNION ALL SELECT withIcon('OpenAI Codex', 'OpenAI'), 7",
    },
}

const cachedResults: HogQLQueryResponse = {
    columns: ['client', 'calls'],
    types: ['Tuple', 'UInt64'],
    results: [
        [['__hx_tag', 'BrandMarkLabel', 'label', 'Claude Code', 'mark', 'Claude'], 12],
        [['__hx_tag', 'BrandMarkLabel', 'label', 'OpenAI Codex', 'mark', 'OpenAI'], 7],
    ],
}

const meta: Meta<typeof DataTable> = {
    title: 'Queries/DataTable/ExplicitIcon',
    component: DataTable,
    parameters: {
        testOptions: { waitForSelector: '[data-attr="hogqlx-brand-mark-label"]' },
    },
}

export default meta

export const QueryResult: StoryObj<typeof DataTable> = {
    render: () => (
        <div className="p-4">
            <DataTable query={query} setQuery={() => {}} cachedResults={cachedResults} readOnly />
        </div>
    ),
}

export const CustomerImages: StoryObj<typeof DataTable> = {
    tags: ['hogqlx-images'],
    parameters: {
        testOptions: { waitForSelector: 'img[alt="Custom SVG"]', viewportWidths: ['narrow', 'wide'] },
    },
    render: () => (
        <div className="p-4">
            <DataTable
                query={{ kind: NodeKind.DataTableNode, source: { kind: NodeKind.HogQLQuery, query: IMAGE_QUERY } }}
                setQuery={() => {}}
                cachedResults={IMAGE_RESULTS}
                readOnly
            />
        </div>
    ),
}
