import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api, { PaginatedResponse } from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { performQuery } from '~/queries/query'
import { DatabaseSchemaQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ExternalDataSource } from '~/types'

import { warehouseTablesList } from 'products/data_warehouse/frontend/generated/api'
import { externalDataSourcesSyncStateRetrieve } from 'products/warehouse_sources/frontend/generated/api'

import { availableSourcesLogic } from '../../../scenes/NewSourceScene/availableSourcesLogic'
import { sourceManagementLogic } from '../sourceManagementLogic'

jest.mock('lib/api')
jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    warehouseTablesList: jest.fn(),
}))
jest.mock('products/warehouse_sources/frontend/generated/api', () => ({
    externalDataSourcesSyncStateRetrieve: jest.fn(),
}))
jest.mock('~/queries/query')

describe('sourceManagementLogic', () => {
    let logic: ReturnType<typeof sourceManagementLogic.build>
    let databaseLogic: ReturnType<typeof databaseTableListLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sourceManagementLogic()
        databaseLogic = databaseTableListLogic()

        jest.spyOn(api.externalDataSources, 'list').mockResolvedValue({
            results: [],
            count: 0,
            next: null,
            previous: null,
        } as PaginatedResponse<ExternalDataSource>)
        jest.spyOn(api.dataWarehouseViewLinks, 'list').mockResolvedValue({
            results: [],
        } as any)

        ;(warehouseTablesList as jest.Mock).mockResolvedValue({
            results: [],
            count: 0,
            next: null,
            previous: null,
        })

        ;(performQuery as jest.Mock).mockResolvedValue({
            tables: {},
            joins: [],
        } as DatabaseSchemaQueryResponse)
        ;(externalDataSourcesSyncStateRetrieve as jest.Mock).mockResolvedValue({ fingerprint: 'fp-1' })
    })

    afterEach(() => {
        logic.unmount()
        databaseLogic.unmount()
    })

    it.each([
        ['display label', 'Google ads'],
        ['internal source_type', 'googleads'],
    ])('finds a managed source by its %s', async (_, searchTerm) => {
        jest.spyOn(api.externalDataSources, 'wizard').mockResolvedValue({
            GoogleAds: { name: 'GoogleAds', label: 'Google Ads' },
        } as any)

        logic.mount()
        await expectLogic(availableSourcesLogic).toDispatchActions(['loadSuccess'])

        sourceManagementLogic.actions.loadSourcesSuccess({
            results: [{ id: 's1', source_type: 'GoogleAds', access_method: 'warehouse', schemas: [] }],
            count: 1,
            next: null,
            previous: null,
        } as any)

        logic.actions.setManagedSearchTerm(searchTerm)
        await expectLogic(logic).toMatchValues({
            filteredManagedSources: [expect.objectContaining({ source_type: 'GoogleAds' })],
        })
    })

    it('lists direct connect sources separately from managed ones', async () => {
        logic.mount()

        sourceManagementLogic.actions.loadSourcesSuccess({
            results: [
                { id: 's1', source_type: 'Stripe', access_method: 'warehouse', schemas: [] },
                { id: 's2', source_type: 'Postgres', prefix: 'prod', access_method: 'direct', schemas: [] },
                { id: 's3', source_type: 'Snowflake', prefix: 'analytics', access_method: 'direct', schemas: [] },
            ],
            count: 3,
            next: null,
            previous: null,
        } as any)

        await expectLogic(logic).toMatchValues({
            managedSources: [expect.objectContaining({ id: 's1' })],
            directSources: [expect.objectContaining({ id: 's2' }), expect.objectContaining({ id: 's3' })],
        })

        logic.actions.setDirectSearchTerm('analytics')
        await expectLogic(logic).toMatchValues({
            filteredDirectSources: [expect.objectContaining({ id: 's3' })],
        })
    })

    it('only includes tables with no source in selfManagedTables', async () => {
        databaseLogic.mount()
        logic.mount()
        databaseTableListLogic.actions.loadDatabaseSuccess({
            tables: {
                no_source_table: {
                    id: 'no-source',
                    type: 'data_warehouse',
                    name: 'no_source_table',
                    fields: {},
                    format: 'Parquet',
                    url_pattern: 'https://bucket/path/*.parquet',
                },
                direct_source_table: {
                    id: 'with-direct-source',
                    type: 'data_warehouse',
                    name: 'direct_source_table',
                    fields: {},
                    format: 'Parquet',
                    url_pattern: 'direct://table',
                    source: {
                        id: 'source-1',
                        status: 'Running',
                        source_type: 'Postgres',
                        prefix: 'prod',
                        access_method: 'direct',
                    },
                },
                warehouse_source_table: {
                    id: 'with-warehouse-source',
                    type: 'data_warehouse',
                    name: 'warehouse_source_table',
                    fields: {},
                    format: 'Parquet',
                    url_pattern: 'warehouse://table',
                    source: {
                        id: 'source-2',
                        status: 'Running',
                        source_type: 'Snowflake',
                        prefix: 'dw',
                        access_method: 'warehouse',
                    },
                },
            },
            joins: [],
        } as DatabaseSchemaQueryResponse)

        await expectLogic(logic).toMatchValues({
            selfManagedTables: [
                expect.objectContaining({
                    name: 'no_source_table',
                }),
            ],
        })
    })

    it('sends one delete when the confirm button is clicked twice', async () => {
        const source = { id: 'source-1', source_type: 'Stripe' } as ExternalDataSource
        let resolveDelete: (() => void) | undefined
        const deleteSource = jest
            .spyOn(api.externalDataSources, 'delete')
            .mockImplementation(() => new Promise<void>((resolve) => (resolveDelete = resolve)))

        logic.mount()
        logic.actions.deleteSource(source)
        logic.actions.deleteSource(source)

        expect(deleteSource).toHaveBeenCalledTimes(1)

        resolveDelete?.()
        await expectLogic(logic).toDispatchActions(['sourceLoadingFinished'])
    })

    it('stops the row spinner when the delete fails', async () => {
        const source = { id: 'source-1', source_type: 'Stripe' } as ExternalDataSource
        jest.spyOn(api.externalDataSources, 'delete').mockRejectedValue(new Error('boom'))

        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSourcesSuccess'])

        logic.actions.deleteSource(source)
        await expectLogic(logic)
            .toDispatchActions(['sourceLoadingFinished'])
            .toNotHaveDispatchedActions(['sourceDeleted'])

        expect(logic.values.sourceReloadingById['source-1']).toBe(false)
        // A transient list failure resolves to an empty page, so reloading after a failed delete
        // would blank a list of sources that still exist.
        expect(logic.values.dataWarehouseSourcesLoading).toBe(false)
    })

    it('does not supersede an in-flight shallow schema load when mounted', async () => {
        let resolveShallowLoad: ((value: DatabaseSchemaQueryResponse) => void) | undefined
        ;(performQuery as jest.Mock).mockImplementationOnce(
            () =>
                new Promise<DatabaseSchemaQueryResponse>((resolve) => {
                    resolveShallowLoad = resolve
                })
        )
        databaseLogic.mount()

        const shallowLoad = databaseLogic.asyncActions.loadDatabase({ shallow: true })
        logic.mount()

        expect(performQuery).toHaveBeenCalledTimes(1)
        expect(performQuery).toHaveBeenCalledWith(expect.objectContaining({ includeFields: false }))

        resolveShallowLoad?.({ tables: {}, joins: [] } as DatabaseSchemaQueryResponse)
        await shallowLoad
    })

    it.each([
        ['nothing is loaded yet', 'none', [false]],
        ['a shallow schema is already loaded', 'shallow-loaded', []],
        ['a consumer starts a full load in the same mount', 'full-alongside', [undefined]],
    ])('loads the schema without fields on mount when %s', async (_, setup, expectedIncludeFields) => {
        databaseLogic.mount()
        if (setup === 'shallow-loaded') {
            await databaseLogic.asyncActions.loadDatabase({ shallow: true })
            ;(performQuery as jest.Mock).mockClear()
        }

        jest.useFakeTimers()
        try {
            logic.mount()
            if (setup === 'full-alongside') {
                databaseLogic.actions.loadDatabase()
            }
            jest.runOnlyPendingTimers()
        } finally {
            jest.useRealTimers()
        }

        expect((performQuery as jest.Mock).mock.calls.map(([query]) => query.includeFields)).toEqual(
            expectedIncludeFields
        )
    })

    it.each([
        ['no linked tables', [], ['orders', 'users', 'events']],
        ['one linked table', ['t-orders'], ['users', 'events']],
        ['all but one table linked', ['t-orders', 't-users'], ['events']],
        ['every self-managed table linked', ['t-orders', 't-users', 't-events'], []],
        ['id of an unknown table', ['t-missing'], ['orders', 'users', 'events']],
    ])('hides tables a managed source will import from the self-managed list: %s', async (_, linkedIds, expected) => {
        ;(warehouseTablesList as jest.Mock).mockResolvedValue({
            results: linkedIds.map((id) => ({ id, pending_source_id: 's2' })),
        })
        databaseLogic.mount()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPendingSelfManagedTableIdsSuccess'])
        databaseTableListLogic.actions.loadDatabaseSuccess({
            tables: {
                orders: { type: 'data_warehouse', id: 't-orders', name: 'orders', fields: {} },
                users: { type: 'data_warehouse', id: 't-users', name: 'users', fields: {} },
                // Linked tables are only hidden when they have no source of their own.
                events: { type: 'data_warehouse', id: 't-events', name: 'events', fields: {} },
                stripe_charges: {
                    type: 'data_warehouse',
                    id: 't-charges',
                    name: 'stripe_charges',
                    fields: {},
                    source: { id: 's1', status: 'Running', source_type: 'Stripe', prefix: '' },
                },
            },
            joins: [],
        } as unknown as DatabaseSchemaQueryResponse)

        expect(warehouseTablesList).toHaveBeenCalledWith(
            expect.anything(),
            expect.objectContaining({ pending_source: true })
        )
        expect(logic.values.selfManagedTables.map((table) => table.name)).toEqual(expected)
        // The sources list shows its self-managed section only while one of these tables is left.
        expect(logic.values.hasSelfManagedTables).toBe(expected.length > 0)
    })
    const unchanged = (): Promise<{ fingerprint: string }> => Promise.resolve({ fingerprint: 'fp-1' })

    it.each([
        ['the sync state is unchanged', unchanged, (): void => {}, false],
        ['the sync state changed', () => Promise.resolve({ fingerprint: 'fp-2' }), (): void => {}, true],
        ['the sync state is unavailable', () => Promise.reject(new Error('offline')), (): void => {}, true],
        [
            'an optimistic update replaced the list',
            unchanged,
            (): void => {
                logic.actions.loadSourcesSuccess({ ...logic.values.dataWarehouseSources!, results: [] })
            },
            true,
        ],
        ['the last list request failed', unchanged, (): void => logic.actions.loadSourcesFailure('boom'), true],
    ])('decides whether a poll refetches the sources list when %s', async (_, nextState, changeList, refetches) => {
        router.actions.push('/data-management/sources')
        logic.mount()
        // The list loads at once on mount; the first poll pairs it with a fingerprint.
        expect(logic.values.dataWarehouseSourcesLoading).toBe(true)
        await expectLogic(logic).toDispatchActions(['loadSourcesSuccess'])
        logic.actions.pollSources()
        await expectLogic(logic)
            .toDispatchActions(['loadSourcesSuccess', 'setFingerprintedSources'])
            .toMatchValues({ fingerprintedSources: expect.objectContaining({ fingerprint: 'fp-1' }) })
        changeList()
        ;(externalDataSourcesSyncStateRetrieve as jest.Mock).mockImplementation(nextState)

        logic.actions.pollSources()

        if (refetches) {
            await expectLogic(logic).toDispatchActions(['loadSources'])
        } else {
            await expectLogic(logic)
                .toDispatchActions(['scheduleSourcesPoll'])
                .toNotHaveDispatchedActions(['loadSources'])
        }
    })
})
