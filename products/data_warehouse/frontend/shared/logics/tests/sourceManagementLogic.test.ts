import { expectLogic } from 'kea-test-utils'

import api, { PaginatedResponse } from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { performQuery } from '~/queries/query'
import { DatabaseSchemaQueryResponse, FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ExternalDataSource } from '~/types'

import { availableSourcesLogic } from '../../../scenes/NewSourceScene/availableSourcesLogic'
import { sourceManagementLogic } from '../sourceManagementLogic'

jest.mock('lib/api')
jest.mock('~/queries/query')

const SORTABLE_SOURCES = [
    { id: 'recent', source_type: 'Stripe', prefix: 'b', last_run_at: '2026-01-02T00:00:00Z' },
    { id: 'starred', source_type: 'Stripe', prefix: 'c', last_run_at: '2026-01-01T00:00:00Z' },
    { id: 'never-run', source_type: 'Stripe', prefix: 'a' },
].map((source) => ({ ...source, access_method: 'warehouse', schemas: [] }) as unknown as ExternalDataSource)

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

        ;(performQuery as jest.Mock).mockResolvedValue({
            tables: {},
            joins: [],
        } as DatabaseSchemaQueryResponse)
    })

    afterEach(() => {
        logic.unmount()
        databaseLogic.unmount()
    })

    const mountWithSortableSources = async (starredSourceIds: string[]): Promise<void> => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSourcesSuccess'])
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        sourceManagementLogic.actions.loadSourcesSuccess({
            results: SORTABLE_SOURCES,
            count: SORTABLE_SOURCES.length,
            next: null,
            previous: null,
        })
        projectTreeDataLogic.actions.loadShortcutsSuccess(
            starredSourceIds.map((id) => ({ id: `shortcut-${id}`, path: id, type: 'data_source', ref: id }))
        )
    }

    it.each([
        ['ascending', 1 as const, '', ['starred', 'never-run', 'recent']],
        ['descending', -1 as const, '', ['starred', 'recent', 'never-run']],
        ['searching', 1 as const, 'stripe', ['never-run', 'starred', 'recent']],
    ])('orders managed sources by last run, %s', async (_, order, searchTerm, expectedIds) => {
        await mountWithSortableSources(['starred'])

        logic.actions.setManagedSearchTerm(searchTerm)
        logic.actions.setManagedSourcesSorting({ columnKey: 'last_run_at', order })

        expect(logic.values.sortedManagedSources.map((source) => source.id)).toEqual(expectedIds)
    })

    it('stars and unstars a source through the sidebar shortcuts', async () => {
        const createShortcut = jest.spyOn(api.fileSystemShortcuts, 'create').mockImplementation(async (data) => ({
            shortcut: { id: 'shortcut-1', ...data } as FileSystemEntry,
            created: true,
        }))
        const deleteShortcut = jest.spyOn(api.fileSystemShortcuts, 'delete').mockResolvedValue()
        await mountWithSortableSources([])

        await expectLogic(logic, () => logic.actions.toggleSourceStarred(SORTABLE_SOURCES[2])).toDispatchActions(
            projectTreeDataLogic,
            ['addShortcutItemSuccess']
        )
        expect(createShortcut).toHaveBeenCalledTimes(1)
        expect(logic.values.sortedManagedSources[0].id).toEqual('never-run')

        await expectLogic(logic, () => logic.actions.toggleSourceStarred(SORTABLE_SOURCES[2])).toDispatchActions(
            projectTreeDataLogic,
            ['deleteShortcutSuccess']
        )
        expect(deleteShortcut).toHaveBeenCalledWith('shortcut-1')
        expect(logic.values.sortedManagedSources[0].id).toEqual('recent')
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

    it('removes the star of a deleted source', async () => {
        jest.spyOn(api.externalDataSources, 'delete').mockResolvedValue()
        const deleteShortcut = jest.spyOn(api.fileSystemShortcuts, 'delete').mockResolvedValue()
        await mountWithSortableSources(['starred'])

        logic.actions.deleteSource(SORTABLE_SOURCES[1])
        await expectLogic(projectTreeDataLogic).toDispatchActions(['deleteShortcutSuccess'])

        expect(deleteShortcut).toHaveBeenCalledWith('shortcut-starred')
    })

    it('stops the row spinner when the delete fails', async () => {
        const source = { id: 'source-1', source_type: 'Stripe' } as ExternalDataSource
        jest.spyOn(api.externalDataSources, 'delete').mockRejectedValue(new Error('boom'))

        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSourcesSuccess'])

        logic.actions.deleteSource(source)
        await expectLogic(logic).toDispatchActions(['sourceLoadingFinished'])

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
})
