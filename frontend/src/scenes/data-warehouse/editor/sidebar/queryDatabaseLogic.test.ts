import { expectLogic } from 'kea-test-utils'

import { newInternalTab } from 'lib/utils/newInternalTab'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { propertyDefinitionsList } from '~/generated/core/api'
import { performQuery } from '~/queries/query'
import type { DatabaseSchemaField } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import {
    getDefaultExpandedRootIds,
    getInitialExpandedFolders,
    getSidebarPropertyDefinitionTarget,
    groupDirectConnectionTableNodesBySchema,
    queryDatabaseLogic,
    shouldInitializeDirectConnectionExpandedFolders,
} from './queryDatabaseLogic'

jest.mock('lib/utils/newInternalTab')
jest.mock('~/generated/core/api', () => ({
    propertyDefinitionsList: jest.fn(),
}))
jest.mock('~/queries/query')

const mockPropertyDefinitionsList = propertyDefinitionsList as jest.Mock

const jsonField = (name = 'properties'): DatabaseSchemaField => ({
    name,
    hogql_value: name,
    type: 'json',
    schema_valid: true,
})

describe('queryDatabaseLogic', () => {
    describe('property definition targets', () => {
        test.each([
            ['event properties', 'events', 'properties', jsonField(), { type: 'event' }],
            ['AI event properties', 'ai_events', 'properties', jsonField(), { type: 'event' }],
            ['person properties', 'persons', 'properties', jsonField(), { type: 'person' }],
            ['person properties joined to events', 'events', 'person.properties', jsonField(), { type: 'person' }],
            [
                'group properties joined to events',
                'events',
                'group_2.properties',
                jsonField(),
                { type: 'group', groupTypeIndex: 2 },
            ],
            [
                'physical person properties',
                'events',
                'person_properties',
                jsonField('person_properties'),
                { type: 'person' },
            ],
            ['ambiguous group properties', 'groups', 'properties', jsonField(), null],
            ['warehouse-shaped JSON', 'events', 'metadata', jsonField('metadata'), null],
            [
                'non-JSON properties',
                'events',
                'properties',
                { ...jsonField(), type: 'string' } as DatabaseSchemaField,
                null,
            ],
        ])('%s map to the stored definition type', (_name, tableName, columnPath, field, expected) => {
            expect(getSidebarPropertyDefinitionTarget(tableName, columnPath, field)).toEqual(expected)
        })
    })

    it('loads pre-expanded properties, paginates, and filters them', async () => {
        initKeaTests()
        mockPropertyDefinitionsList
            .mockReset()
            .mockResolvedValueOnce({
                count: 3,
                results: [
                    { id: 'browser', name: '$browser', property_type: 'String' },
                    {
                        id: 'quoted-property',
                        name: '"foo" OR 1=1 OR properties."foo"',
                        property_type: 'String',
                    },
                ],
            })
            .mockResolvedValueOnce({
                count: 3,
                results: [{ id: 'checkout-step', name: 'checkout.step', property_type: 'Numeric' }],
            })
            .mockResolvedValueOnce({
                count: 1,
                results: [{ id: 'browser', name: '$browser', property_type: 'String' }],
            })
        const logic = queryDatabaseLogic()
        logic.mount()
        logic.actions.setExpandedFolders(['sources', 'property-events-properties'])
        await expectLogic(logic, () =>
            databaseTableListLogic.findMounted()?.actions.loadDatabaseSuccess({
                tables: {
                    events: {
                        id: 'events',
                        name: 'events',
                        type: 'posthog',
                        fields: { properties: jsonField() },
                    },
                },
                joins: [],
            })
        ).toDispatchActions(['loadPropertyDefinitionsSuccess'])

        const propertyNode = (): NonNullable<(typeof logic.values.treeData)[number]> | undefined =>
            logic.values.treeData
                .find((item) => item.record?.type === 'sources')
                ?.children?.find((item) => item.name === 'PostHog')
                ?.children?.find((item) => item.name === 'events')
                ?.children?.find((item) => item.record?.type === 'property-field')

        expect(propertyNode()?.record?.propertyDefinitionTarget).toEqual({ type: 'event' })
        expect(mockPropertyDefinitionsList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ limit: 25, offset: 0, type: 'event' })
        )
        expect(propertyNode()?.children?.map((item) => item.name)).toEqual([
            '$browser',
            '"foo" OR 1=1 OR properties."foo"',
            'Load more',
        ])
        expect(propertyNode()?.children?.[1].record?.hogqlExpression).toEqual(
            'properties.`"foo" OR 1=1 OR properties."foo"`'
        )

        await expectLogic(logic, () =>
            propertyNode()
                ?.children?.find((item) => item.record?.type === 'property-definitions-load-more')
                ?.onClick?.()
        ).toDispatchActions(['loadPropertyDefinitionsSuccess'])

        expect(mockPropertyDefinitionsList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ offset: 2, type: 'event' })
        )
        expect(propertyNode()?.children?.map((item) => item.name)).toEqual([
            '$browser',
            '"foo" OR 1=1 OR properties."foo"',
            'checkout.step',
        ])
        expect(propertyNode()?.children?.[2].record?.hogqlExpression).toEqual('properties."checkout.step"')

        await expectLogic(logic, () =>
            logic.actions.setPropertyDefinitionSearch('events:properties', { type: 'event' }, 'browser')
        ).toDispatchActions(['loadPropertyDefinitionsSuccess'])

        expect(mockPropertyDefinitionsList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ offset: 0, search: 'browser', type: 'event' })
        )
        databaseTableListLogic.findMounted()?.actions.loadDatabaseSuccess({
            tables: {
                events: {
                    id: 'events',
                    name: 'events',
                    type: 'posthog',
                    fields: { properties: jsonField() },
                },
            },
            joins: [],
        })
        expect(propertyNode()?.children?.map((item) => item.name)).toEqual(['$browser'])
        expect(propertyNode()?.record?.propertyDefinitionSearch).toEqual('browser')

        const browserDefinition = logic.values.propertyDefinitionLists['events:properties'].definitions[0]
        expect(propertyNode()?.children?.[0].record?.propertyDefinition).toEqual(browserDefinition)

        logic.actions.openPropertyDefinitionEditor(browserDefinition)
        expect(logic.values.editingPropertyDefinition).toEqual(browserDefinition)

        logic.actions.updatePropertyDefinition({ ...browserDefinition, property_type: 'Boolean' })
        expect(propertyNode()?.children?.[0].record?.field.type).toEqual('boolean')
        expect(propertyNode()?.children?.[0].record?.propertyDefinition.property_type).toEqual('Boolean')
        expect(logic.values.editingPropertyDefinition).toBeNull()

        logic.actions.updatePropertyDefinition({ ...browserDefinition, hidden: true })
        expect(propertyNode()?.children?.map((item) => item.name)).toEqual(['No matching properties'])

        logic.unmount()
    })

    it('keeps newer property results when overlapping requests resolve out of order', async () => {
        initKeaTests()
        let releaseStaleResponse = (): void => {}
        const staleResponseReleased = new Promise<void>((resolve) => {
            releaseStaleResponse = resolve
        })
        mockPropertyDefinitionsList
            .mockReset()
            .mockImplementationOnce(async () => {
                await staleResponseReleased
                return {
                    count: 1,
                    results: [{ id: 'stale', name: 'stale', property_type: 'String' }],
                }
            })
            .mockResolvedValueOnce({
                count: 1,
                results: [{ id: 'fresh', name: 'fresh', property_type: 'String' }],
            })
        const logic = queryDatabaseLogic()
        logic.mount()

        logic.actions.loadPropertyDefinitions('events:properties', { type: 'event' }, 0)
        await expectLogic(logic, () =>
            logic.actions.loadPropertyDefinitions('events:properties', { type: 'event' }, 0)
        ).toDispatchActions(['loadPropertyDefinitionsSuccess'])
        expect(logic.values.propertyDefinitionLists['events:properties'].definitions.map(({ name }) => name)).toEqual([
            'fresh',
        ])

        releaseStaleResponse()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.propertyDefinitionLists['events:properties'].definitions.map(({ name }) => name)).toEqual([
            'fresh',
        ])
        logic.unmount()
    })

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
