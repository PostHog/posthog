import { expectLogic } from 'kea-test-utils'

import api, { PaginatedResponse } from 'lib/api'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { performQuery } from '~/queries/query'
import { DatabaseSchemaQueryResponse, FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ExternalDataSource } from '~/types'

import { managedSourcesTableLogic } from '../managedSourcesTableLogic'
import { sourceManagementLogic } from '../sourceManagementLogic'

jest.mock('lib/api')
jest.mock('~/queries/query')

const SOURCES = [
    {
        id: 'recent',
        source_type: 'Stripe',
        prefix: 'b',
        status: 'Completed',
        last_run_at: '2026-01-02T00:00:00Z',
        schemas: [{ id: 'schema-1', should_sync: true, status: 'Paused' }],
    },
    {
        id: 'starred',
        source_type: 'Stripe',
        prefix: 'c',
        status: 'Completed',
        last_run_at: '2026-01-01T00:00:00Z',
        schemas: [],
    },
    { id: 'never-run', source_type: 'Stripe', prefix: 'a', status: 'Error', schemas: [] },
].map((source) => ({ ...source, access_method: 'warehouse' }) as unknown as ExternalDataSource)

const source = (id: string): ExternalDataSource => SOURCES.find((s) => s.id === id) as ExternalDataSource

describe('managedSourcesTableLogic', () => {
    let logic: ReturnType<typeof managedSourcesTableLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.spyOn(api.externalDataSources, 'list').mockResolvedValue({
            results: [],
            count: 0,
            next: null,
            previous: null,
        } as PaginatedResponse<ExternalDataSource>)
        jest.spyOn(api.dataWarehouseViewLinks, 'list').mockResolvedValue({ results: [] } as any)
        ;(performQuery as jest.Mock).mockResolvedValue({ tables: {}, joins: [] } as DatabaseSchemaQueryResponse)

        logic = managedSourcesTableLogic()
        logic.mount()
        await expectLogic(sourceManagementLogic).toDispatchActions(['loadSourcesSuccess'])
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        sourceManagementLogic.actions.loadSourcesSuccess({
            results: SOURCES,
            count: SOURCES.length,
            next: null,
            previous: null,
        })
    })

    afterEach(() => {
        logic.unmount()
    })

    const starSources = (ids: string[]): void => {
        projectTreeDataLogic.actions.loadShortcutsSuccess(
            ids.map((id) => ({ id: `shortcut-${id}`, path: id, type: 'data_source', ref: id }))
        )
    }

    it.each([
        ['last run, ascending', 'last_run_at', 1 as const, '', ['starred', 'never-run', 'recent']],
        ['last run, descending', 'last_run_at', -1 as const, '', ['starred', 'recent', 'never-run']],
        ['last run, while searching', 'last_run_at', 1 as const, 'stripe', ['never-run', 'starred', 'recent']],
        ['status, with a backend error status', 'status', 1 as const, '', ['starred', 'never-run', 'recent']],
    ])('orders managed sources by %s', (_, columnKey, order, searchTerm, expectedIds) => {
        starSources(['starred'])

        sourceManagementLogic.actions.setManagedSearchTerm(searchTerm)
        logic.actions.setManagedSourcesSorting({ columnKey, order })

        expect(logic.values.sortedManagedSources.map((s) => s.id)).toEqual(expectedIds)
    })

    it('stars and unstars a source through the sidebar shortcuts', async () => {
        const createShortcut = jest.spyOn(api.fileSystemShortcuts, 'create').mockImplementation(async (data) => ({
            shortcut: { id: 'shortcut-1', ...data } as FileSystemEntry,
            created: true,
        }))
        const deleteShortcut = jest.spyOn(api.fileSystemShortcuts, 'delete').mockResolvedValue()
        starSources([])

        await expectLogic(logic, () => logic.actions.toggleSourceStarred(source('never-run'))).toDispatchActions(
            projectTreeDataLogic,
            ['addShortcutItemSuccess']
        )
        expect(createShortcut).toHaveBeenCalledTimes(1)
        expect(logic.values.sortedManagedSources[0].id).toEqual('never-run')

        await expectLogic(logic, () => logic.actions.toggleSourceStarred(source('never-run'))).toDispatchActions(
            projectTreeDataLogic,
            ['deleteShortcutSuccess']
        )
        expect(deleteShortcut).toHaveBeenCalledWith('shortcut-1')
        expect(logic.values.sortedManagedSources[0].id).toEqual('recent')
    })

    it('removes the star of a deleted source', async () => {
        jest.spyOn(api.externalDataSources, 'delete').mockResolvedValue()
        const deleteShortcut = jest.spyOn(api.fileSystemShortcuts, 'delete').mockResolvedValue()
        starSources(['starred'])

        sourceManagementLogic.actions.deleteSource(source('starred'))
        await expectLogic(projectTreeDataLogic).toDispatchActions(['deleteShortcutSuccess'])

        expect(deleteShortcut).toHaveBeenCalledWith('shortcut-starred')
    })
})
