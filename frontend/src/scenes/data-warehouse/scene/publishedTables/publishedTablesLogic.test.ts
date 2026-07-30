import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PublishedTableApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { publishedTablesLogic } from './publishedTablesLogic'

const publication = (status: PublishedTableApi['status']): PublishedTableApi => ({
    id: '5c98d849-1119-4207-bba2-5161b31a4067',
    table_id: status === 'completed' ? '717e15ee-24ff-4172-83f6-8a43aebf8da0' : null,
    name: 'main_customers',
    source_schema_name: 'main',
    source_table_name: 'customers',
    status,
    last_published_at: status === 'completed' ? '2026-07-30T08:00:00Z' : null,
    last_error: null,
    row_count: status === 'completed' ? 42 : null,
})

describe('publishedTablesLogic', () => {
    let logic: ReturnType<typeof publishedTablesLogic.build>

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
    })

    it('polls while a publication is active and stops when it completes', async () => {
        jest.useFakeTimers()
        let status: PublishedTableApi['status'] = 'pending'
        let listCalls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-published-tables/': () => {
                    listCalls += 1
                    return [200, { results: [publication(status)] }]
                },
            },
        })
        initKeaTests()
        logic = publishedTablesLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPublishedTablesSuccess'])

        expect(listCalls).toBe(1)
        await jest.advanceTimersByTimeAsync(5000)
        expect(listCalls).toBe(2)

        status = 'completed'
        await jest.advanceTimersByTimeAsync(5000)
        expect(listCalls).toBe(3)
        expect(logic.values.hasActivePublications).toBe(false)

        await jest.advanceTimersByTimeAsync(20000)
        expect(listCalls).toBe(3)
    })

    it('loads modeled tables on demand and submits the selected source', async () => {
        let requestBody: Record<string, unknown> | null = null
        useMocks({
            get: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-published-tables/': [200, { results: [] }],
                '/api/projects/:team_id/data_warehouse/managed-warehouse-modeled-tables/': [
                    200,
                    { results: [{ schema_name: 'main', table_name: 'customers' }] },
                ],
            },
            post: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-publish-table/': async ({ request }) => {
                    requestBody = (await request.json()) as Record<string, unknown>
                    return [201, publication('pending')]
                },
            },
        })
        initKeaTests()
        logic = publishedTablesLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPublishedTablesSuccess'])

        await expectLogic(logic, () => logic.actions.openPublishModal()).toDispatchActions(['loadModeledTablesSuccess'])
        logic.actions.setPublishTableValues({ sourceTableKey: 'main.customers', name: 'customers_snapshot' })

        await expectLogic(logic, () => logic.actions.submitPublishTable())
            .toDispatchActions(['closePublishModal', 'loadPublishedTables', 'submitPublishTableSuccess'])
            .toFinishAllListeners()

        expect(requestBody).toEqual({
            source_schema_name: 'main',
            source_table_name: 'customers',
            name: 'customers_snapshot',
        })
        expect(logic.values.publishModalOpen).toBe(false)
        expect(logic.values.publishTable).toEqual({ sourceTableKey: '', name: '' })
    })

    it('filters by publication name and modeled source', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-published-tables/': [
                    200,
                    { results: [publication('completed')] },
                ],
            },
        })
        initKeaTests()
        logic = publishedTablesLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPublishedTablesSuccess'])

        logic.actions.setSearchTerm('customers')
        expect(logic.values.filteredPublishedTables).toHaveLength(1)
        logic.actions.setSearchTerm('orders')
        expect(logic.values.filteredPublishedTables).toHaveLength(0)
    })
})
