import { expectLogic } from 'kea-test-utils'

import { newInternalTab } from 'lib/utils/newInternalTab'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import {
    getDefaultExpandedRootIds,
    getInitialExpandedFolders,
    groupDirectConnectionTableNodesBySchema,
    queryDatabaseLogic,
    shouldInitializeDirectConnectionExpandedFolders,
} from './queryDatabaseLogic'

jest.mock('lib/utils/newInternalTab')
jest.mock('~/queries/query')

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

    it('opens and focuses a located table after the collapsed tree remounts', () => {
        initKeaTests()
        const logic = queryDatabaseLogic()
        logic.mount()
        databaseTableListLogic.findMounted()?.actions.loadDatabaseSuccess({
            tables: {
                events: {
                    id: 'events',
                    name: 'events',
                    type: 'posthog',
                    fields: {},
                },
            },
            joins: [],
        })
        const focusItem = jest.fn()

        logic.actions.locateTable('events')

        expect(logic.values.expandedFolders).toEqual(
            expect.arrayContaining(['sources', 'source-posthog', 'table-events'])
        )
        expect(logic.values.tableToLocate).toEqual('events')

        logic.actions.setTreeRef({
            current: {
                focusItem,
                getVisibleItems: () => [],
            },
        })

        expect(focusItem).toHaveBeenCalledWith('table-events', {
            scrollPosition: 'top-third',
            behavior: 'smooth',
        })
        expect(logic.values.tableToLocate).toBeNull()

        logic.unmount()
    })

    describe('failed schema load', () => {
        let logic: ReturnType<typeof queryDatabaseLogic.build>

        const childNames = (sectionType: string): (string | undefined)[] =>
            logic.values.treeData
                .find((item) => item.record?.type === sectionType)
                ?.children?.map((child) => child.name) ?? []

        beforeEach(() => {
            initKeaTests()
            logic = queryDatabaseLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
        })

        it('shows the failure and a retry instead of an empty tree', () => {
            databaseTableListLogic.findMounted()?.actions.loadDatabaseFailure('A server error occurred.')

            expect(childNames('sources')).toEqual(["Couldn't load your schema", 'Try again'])
            expect(childNames('managed-views')).toEqual(["Couldn't load your schema", 'Try again'])
        })

        it('retries the schema load when the retry node is clicked', () => {
            databaseTableListLogic.findMounted()?.actions.loadDatabaseFailure('A server error occurred.')

            const retryNode = logic.values.treeData
                .find((item) => item.record?.type === 'sources')
                ?.children?.find((child) => child.record?.type === 'schema-load-retry')

            retryNode?.onClick?.()

            expect(logic.values.databaseLoadError).toEqual(null)
            expect(childNames('sources')).not.toContain("Couldn't load your schema")
        })
    })

    describe('lazy schema hydration', () => {
        let logic: ReturnType<typeof queryDatabaseLogic.build>
        let dbLogic: ReturnType<typeof databaseTableListLogic.build>

        const findTableNode = (): any =>
            logic.values.treeData
                .find((item) => item.record?.type === 'sources')
                ?.children?.find((child) => child.id === 'source-posthog')
                ?.children?.find((child) => child.id === 'table-events')

        beforeEach(async () => {
            initKeaTests()
            // Earlier tests persist expanded folders; a restored expansion would trigger hydration
            // before the assertions below stage their own state.
            localStorage.clear()
            ;(performQuery as jest.Mock).mockResolvedValue({ tables: {}, joins: [] })
            logic = queryDatabaseLogic()
            logic.mount()
            dbLogic = databaseTableListLogic.findMounted()! as ReturnType<typeof databaseTableListLogic.build>
            await expectLogic(dbLogic).toFinishAllListeners()
            dbLogic.actions.loadDatabaseSuccess({
                tables: { events: { id: 'events', name: 'events', type: 'posthog', fields: {} } },
                joins: [],
            })
            dbLogic.actions.setDatabaseFieldsComplete(false)
        })

        afterEach(() => {
            logic.unmount()
            jest.clearAllMocks()
        })

        it('renders a hydration placeholder, hydrates on expand, then shows the columns', async () => {
            const placeholder = findTableNode()?.children?.[0]
            expect(placeholder?.type).toEqual('loading-indicator')
            expect(placeholder?.record?.pendingTableName).toEqual('events')

            logic.actions.toggleFolderOpen('table-events', false)
            await expectLogic(dbLogic).toFinishAllListeners()

            expect(performQuery).toHaveBeenCalledWith(expect.objectContaining({ tables: ['events'] }))

            dbLogic.actions.hydrateTableFieldsSuccess(['events'], {
                events: {
                    id: 'events',
                    name: 'events',
                    type: 'posthog',
                    fields: { uuid: { name: 'uuid', hogql_value: 'uuid', type: 'string', schema_valid: true } },
                } as any,
            })

            const columnNames = findTableNode()?.children?.map((child: any) => child.name)
            expect(columnNames).toEqual(['uuid'])
        })

        it('shows an error node when hydrating a table failed', () => {
            dbLogic.actions.hydrateTableFieldsStart(['events'])
            dbLogic.actions.hydrateTableFieldsFailure(['events'])

            const errorNode = findTableNode()?.children?.[0]
            expect(errorNode?.record?.type).toEqual('fields-load-error')
        })
    })

    describe('direct connection state', () => {
        let logic: ReturnType<typeof queryDatabaseLogic.build>

        beforeEach(async () => {
            initKeaTests()
            ;(performQuery as jest.Mock).mockResolvedValue({ tables: {}, joins: [] })
            logic = queryDatabaseLogic()
            logic.mount()
            const databaseLogic = databaseTableListLogic.findMounted()!
            await expectLogic(databaseLogic).toFinishAllListeners()
            databaseLogic.actions.setConnection('source-id')
            ;(performQuery as jest.Mock).mockClear()
        })

        afterEach(() => {
            logic.unmount()
            jest.clearAllMocks()
        })

        it('shows a direct schema failure and retry at the root of the sidebar', () => {
            databaseTableListLogic.findMounted()?.actions.loadDatabaseFailure('Connection failed.')

            expect(logic.values.displayedTreeData.map((item) => item.name)).toEqual([
                "Couldn't load your schema",
                'Try again',
            ])
        })

        it('links an empty direct schema to table configuration', () => {
            databaseTableListLogic.findMounted()?.actions.loadDatabaseSuccess({ tables: {}, joins: [] })

            expect(logic.values.displayedTreeData.map((item) => item.name)).toEqual([
                'No queryable tables',
                'Configure tables',
            ])

            logic.values.displayedTreeData
                .find((item) => item.record?.type === 'direct-connection-configure')
                ?.onClick?.()

            expect(newInternalTab).toHaveBeenCalledWith(
                expect.stringContaining('/data-management/sources/managed-source-id/schemas')
            )
        })

        it('hydrates a table restored as expanded in the displayed direct-connection tree', async () => {
            const databaseLogic = databaseTableListLogic.findMounted()!
            databaseLogic.actions.loadDatabaseSuccess({
                tables: {
                    'public.accounts': {
                        id: 'accounts',
                        name: 'public.accounts',
                        type: 'data_warehouse',
                        fields: {},
                        source: {
                            id: 'source-id',
                            status: 'Running',
                            source_type: 'Postgres',
                            prefix: '',
                            access_method: 'direct',
                        },
                    },
                },
                joins: [],
            } as any)
            databaseLogic.actions.setDatabaseFieldsComplete(false)
            ;(performQuery as jest.Mock).mockResolvedValueOnce({
                tables: {
                    'public.accounts': {
                        id: 'accounts',
                        name: 'public.accounts',
                        type: 'data_warehouse',
                        fields: {
                            id: { name: 'id', hogql_value: 'id', type: 'string', schema_valid: true },
                        },
                    },
                },
                joins: [],
            })

            logic.actions.setExpandedFolders(['schema-public', 'table-public.accounts'], 'source-id')
            await expectLogic(databaseLogic).toFinishAllListeners()

            expect(performQuery).toHaveBeenCalledWith(expect.objectContaining({ tables: ['public.accounts'] }))
            expect(databaseLogic.values.database?.tables['public.accounts'].fields).toHaveProperty('id')
        })
    })
})
