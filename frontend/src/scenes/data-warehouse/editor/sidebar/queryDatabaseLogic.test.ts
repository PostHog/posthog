import {
    getDefaultExpandedRootIds,
    getInitialExpandedFolders,
    groupDirectConnectionTableNodesBySchema,
    shouldInitializeDirectConnectionExpandedFolders,
} from './queryDatabaseLogic'

describe('queryDatabaseLogic', () => {
    it('groups direct connection tables into schema folders', () => {
        const grouped = groupDirectConnectionTableNodesBySchema(
            [
                {
                    id: 'table-system.query_log',
                    name: 'system.query_log',
                    type: 'node',
                    record: {
                        type: 'table',
                        table: { name: 'system.query_log' },
                    },
                },
                {
                    id: 'table-system.checkpoints',
                    name: 'system.checkpoints',
                    type: 'node',
                    record: {
                        type: 'table',
                        table: { name: 'system.checkpoints' },
                    },
                },
                {
                    id: 'table-public.accounts',
                    name: 'public.accounts',
                    type: 'node',
                    record: {
                        type: 'table',
                        table: { name: 'public.accounts' },
                    },
                },
            ] as any,
            false
        )

        expect(grouped.map((item) => item.name)).toEqual(['public', 'system'])
        expect(grouped.every((item) => item.icon)).toEqual(true)
        expect(grouped[0].children?.map((item) => item.name)).toEqual(['public.accounts'])
        expect(grouped[1].children?.map((item) => item.name)).toEqual(['system.checkpoints', 'system.query_log'])
        expect(grouped[0].children?.map((item) => item.displayName)).toEqual(['accounts'])
        expect(grouped[1].children?.map((item) => item.displayName)).toEqual(['checkpoints', 'query_log'])
    })

    it('uses the selected source schema when table names are unqualified', () => {
        const grouped = groupDirectConnectionTableNodesBySchema(
            [
                {
                    id: 'table-accounts',
                    name: 'accounts',
                    type: 'node',
                    record: {
                        type: 'table',
                        table: { name: 'accounts' },
                    },
                },
                {
                    id: 'table-events',
                    name: 'events',
                    type: 'node',
                    record: {
                        type: 'table',
                        table: { name: 'events' },
                    },
                },
            ] as any,
            false,
            'analytics'
        )

        expect(grouped.map((item) => item.name)).toEqual(['analytics'])
        expect(grouped[0].icon).toBeTruthy()
        expect(grouped[0].children?.map((item) => item.name)).toEqual(['accounts', 'events'])
        expect(grouped[0].children?.map((item) => item.displayName)).toEqual(['accounts', 'events'])
    })

    it('does not force schema folders open in direct connection mode', () => {
        expect(
            getDefaultExpandedRootIds('source-id', [
                {
                    id: 'schema-system',
                    name: 'system',
                    type: 'node',
                    record: { type: 'source-folder', sourceType: 'system' },
                },
                {
                    id: 'views',
                    name: 'Views',
                    type: 'node',
                    record: { type: 'views' },
                },
            ] as any)
        ).toEqual(['views'])
    })

    it('keeps loading schema folders expanded in direct connection mode', () => {
        expect(
            getDefaultExpandedRootIds('source-id', [
                {
                    id: 'schema-ungrouped',
                    name: 'Tables',
                    type: 'node',
                    record: { type: 'source-folder', sourceType: 'Tables' },
                    children: [
                        {
                            id: 'sources-loading/',
                            name: 'Loading...',
                            type: 'loading-indicator',
                        },
                    ],
                },
                {
                    id: 'views',
                    name: 'Views',
                    type: 'node',
                    record: { type: 'views' },
                },
            ] as any)
        ).toEqual(['schema-ungrouped', 'views'])
    })

    it('expands all schema folders by default for a direct connection', () => {
        expect(
            getInitialExpandedFolders('source-id', [
                {
                    id: 'schema-system',
                    name: 'system',
                    type: 'node',
                    record: { type: 'source-folder', sourceType: 'system' },
                },
                {
                    id: 'schema-public',
                    name: 'public',
                    type: 'node',
                    record: { type: 'source-folder', sourceType: 'public' },
                },
                {
                    id: 'views',
                    name: 'Views',
                    type: 'node',
                    record: { type: 'views' },
                },
            ] as any)
        ).toEqual(expect.arrayContaining(['schema-system', 'schema-public', 'views']))
    })

    it('reinitializes direct connection folders when only legacy defaults are expanded', () => {
        expect(
            shouldInitializeDirectConnectionExpandedFolders(
                [
                    {
                        id: 'schema-system',
                        name: 'system',
                        type: 'node',
                        record: { type: 'source-folder', sourceType: 'system' },
                    },
                    {
                        id: 'schema-public',
                        name: 'public',
                        type: 'node',
                        record: { type: 'source-folder', sourceType: 'public' },
                    },
                    {
                        id: 'views',
                        name: 'Views',
                        type: 'node',
                        record: { type: 'views' },
                    },
                ] as any,
                ['sources', 'views', 'managed-views']
            )
        ).toEqual(true)
    })

    it('does not reinitialize direct connection folders after schema folders are already expanded', () => {
        expect(
            shouldInitializeDirectConnectionExpandedFolders(
                [
                    {
                        id: 'schema-system',
                        name: 'system',
                        type: 'node',
                        record: { type: 'source-folder', sourceType: 'system' },
                    },
                    {
                        id: 'views',
                        name: 'Views',
                        type: 'node',
                        record: { type: 'views' },
                    },
                ] as any,
                ['views', 'schema-system']
            )
        ).toEqual(false)
    })
})
