import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { BIDataSource, getBIDataSourceKey } from 'scenes/data-warehouse/editor/bi/biEditorTypes'

import { buildBIDataSourceTree, searchBIDataSourceTree } from './biDataSourceTree'

const tree: TreeDataItem[] = [
    {
        id: 'sources',
        name: 'Sources',
        record: { type: 'sources' },
        children: [
            {
                id: 'postgres',
                name: 'Postgres',
                record: { type: 'source-folder' },
                children: [
                    {
                        id: 'orders',
                        name: 'sales.orders',
                        record: { type: 'table' },
                        children: [{ id: 'field', name: 'sales.customers', record: { type: 'column' } }],
                    },
                    { id: 'customers', name: 'sales.customers', record: { type: 'table' } },
                ],
            },
            {
                id: 'stripe',
                name: 'Stripe',
                record: { type: 'source-folder' },
                children: [{ id: 'invoices', name: 'invoices', record: { type: 'table' } }],
            },
        ],
    },
    { id: 'drafts', name: 'Drafts', children: [{ id: 'draft', name: 'draft', record: { type: 'draft' } }] },
]

const sources: BIDataSource[] = [{ table: 'sales.orders' }, { table: 'sales.customers' }, { table: 'invoices' }]

it.each([
    ['orders', ['sales.orders']],
    [' POSTGRES ', ['sales.orders', 'sales.customers']],
    ['missing', []],
])('searches tables and ancestor folders for %s', (search, names) => {
    const results = searchBIDataSourceTree(buildBIDataSourceTree(tree, sources, false), search)
    expect(
        results.flatMap(
            (root) => root.children?.flatMap((group) => group.children?.map((leaf) => leaf.name) ?? []) ?? []
        )
    ).toEqual(names)
    if (names.length) {
        expect(results[0].name).toBe('Sources')
        expect(results[0].children?.[0].name).toBe('Postgres')
    }
})

it('keeps selectable sources as leaves and preserves a source missing from the tree', () => {
    const results = buildBIDataSourceTree(tree, [...sources, { table: 'saved_view' }], false)
    expect(results.map((node) => node.name)).toEqual(['Sources', 'saved_view'])
    const tables = results[0].children!.flatMap((folder) => folder.children!)
    expect(tables.map((node) => node.id)).toEqual(sources.map(getBIDataSourceKey))
    expect(tables.every((node) => !node.children)).toBe(true)
    expect(results[1].id).toBe(getBIDataSourceKey({ table: 'saved_view' }))
})

it('groups direct connection tables by schema without losing connection identity', () => {
    const connectionSources = sources.map((source) => ({ ...source, connectionId: 'example-connection' }))
    const results = buildBIDataSourceTree(tree, connectionSources, true, 'public')
    expect(results.map((node) => node.name)).toEqual(['public', 'sales'])
    expect(results[1].children?.map((node) => [node.displayName, node.id])).toEqual([
        ['customers', getBIDataSourceKey(connectionSources[1])],
        ['orders', getBIDataSourceKey(connectionSources[0])],
    ])
})
