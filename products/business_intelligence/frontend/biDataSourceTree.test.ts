import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { BIDataSource } from '~/queries/schema/schema-business-intelligence'
import { DatabaseSchemaTable } from '~/queries/schema/schema-general'

import { buildBIDataSourceTree, searchBIDataSourceTree } from 'products/business_intelligence/frontend/biDataSourceTree'
import { getBIDataSourceKey } from 'products/business_intelligence/frontend/biEditorTypes'

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

describe('BI data source tree', () => {
    it.each([false, true])('preserves trust metadata and prioritizes certified sources (direct: %s)', (direct) => {
        const certification = { status: 'certified' as const, notes: 'Reviewed example totals' }
        const tables: DatabaseSchemaTable[] = [
            {
                id: 'old',
                name: 'sales.old_orders',
                type: 'posthog',
                fields: {},
                certification: { status: 'deprecated' },
            },
            { id: 'raw', name: 'sales.raw_orders', type: 'posthog', fields: {} },
            { id: 'orders', name: 'sales.orders', type: 'posthog', fields: {}, certification },
        ]
        const connectionId = direct ? 'example-connection' : undefined
        const savedSource = { table: 'sales.orders', connectionId: 'another-connection' }
        const results = buildBIDataSourceTree(
            [
                {
                    id: 'tables',
                    name: 'Tables',
                    children: tables.map((table) => ({
                        id: table.id,
                        name: table.name,
                        record: { type: 'table', certification: table.certification },
                    })),
                },
            ],
            [...tables.map(({ name }) => ({ table: name, connectionId })), savedSource],
            direct,
            'public',
            connectionId
        )
        const leaves = (nodes: TreeDataItem[]): TreeDataItem[] =>
            nodes.flatMap((node) => (node.children ? leaves(node.children) : [node]))
        const matched = leaves(searchBIDataSourceTree(results, 'orders'))
        const current = matched.filter((node) => node.id !== getBIDataSourceKey(savedSource))
        expect(current.map((node) => node.name)).toEqual(['sales.orders', 'sales.raw_orders', 'sales.old_orders'])
        expect(current[0].record?.certification).toEqual(certification)
        expect(
            matched.find((node) => node.id === getBIDataSourceKey(savedSource))?.record?.certification
        ).toBeUndefined()
    })

    it('prioritizes folders by their matching sources after search', () => {
        const results = buildBIDataSourceTree(
            [
                { id: 'raw', name: 'Raw', children: [{ id: 'a', name: 'orders_raw', record: { type: 'table' } }] },
                {
                    id: 'views',
                    name: 'Views',
                    children: [
                        {
                            id: 'b',
                            name: 'customers',
                            record: { type: 'view', certification: { status: 'certified' } },
                        },
                        {
                            id: 'c',
                            name: 'orders_old',
                            record: { type: 'view', certification: { status: 'deprecated' } },
                        },
                    ],
                },
            ],
            [{ table: 'orders_raw' }, { table: 'customers' }, { table: 'orders_old' }],
            false
        )
        expect(results.map((node) => node.name)).toEqual(['Certified sources', 'Raw', 'Views'])
        expect(searchBIDataSourceTree(results, 'orders').map((node) => node.name)).toEqual(['Raw', 'Views'])
    })
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
        const results = buildBIDataSourceTree(tree, connectionSources, true, 'public', 'example-connection')
        expect(results.map((node) => node.name)).toEqual(['public', 'sales'])
        expect(results[1].children?.map((node) => [node.displayName, node.id])).toEqual([
            ['customers', getBIDataSourceKey(connectionSources[1])],
            ['orders', getBIDataSourceKey(connectionSources[0])],
        ])
    })

    it('preserves a saved source from another connection with the same table name', () => {
        const saved = { table: 'sales.orders', connectionId: 'saved-connection' }
        const results = buildBIDataSourceTree(tree, [saved, ...sources], false)
        expect(results[0].children![0].children![0].id).toBe(getBIDataSourceKey(sources[0]))
        expect(results[1].id).toBe(getBIDataSourceKey(saved))
    })

    it('keeps versioned endpoints under their folder with their icon', () => {
        const endpoint = { table: 'report_v1' }
        const icon = 'endpoint-icon'
        const results = buildBIDataSourceTree(
            [
                {
                    id: 'views',
                    name: 'Views',
                    children: [
                        { id: 'endpoint', name: 'report', icon, record: { type: 'endpoint', tableName: 'report_v1' } },
                    ],
                },
            ],
            [endpoint],
            false
        )
        expect(searchBIDataSourceTree(results, 'Views')).toEqual(results)
        expect(results).toHaveLength(1)
        expect(results[0].children).toEqual([
            {
                id: getBIDataSourceKey(endpoint),
                name: 'report_v1',
                icon,
                record: { type: 'endpoint', tableName: 'report_v1' },
            },
        ])
    })
})
