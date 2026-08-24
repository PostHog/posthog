import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PublishedTableApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { publishedTablesLogic } from './publishedTablesLogic'

const makePublication = (status: PublishedTableApi['status']): PublishedTableApi => ({
    id: '5c98d849-1119-4207-bba2-5161b31a4067',
    saved_query_id: '79da0bb6-0906-4187-b2ad-34fb70f45c17',
    name: 'modeled_customers',
    source_schema_name: 'posthog_data_modeling_team_2',
    source_table_name: 'customers',
    status,
    last_published_at: status === 'completed' ? '2026-08-24T08:00:00Z' : null,
    last_error: null,
    row_count: status === 'completed' ? 42 : null,
})

describe('publishedTablesLogic', () => {
    let logic: ReturnType<typeof publishedTablesLogic.build>

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
    })

    it('publishes the selected warehouse table and refreshes the list', async () => {
        let requestBody: Record<string, unknown> | null = null
        let listCalls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-published-tables/': () => {
                    listCalls += 1
                    return [200, { results: [] }]
                },
                '/api/projects/:team_id/data_warehouse/managed-warehouse-modeled-tables/': [
                    200,
                    {
                        results: [
                            {
                                schema_name: 'analytics',
                                table_name: 'customers',
                                publishable: true,
                                disabled_reason: null,
                            },
                        ],
                    },
                ],
            },
            post: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-publish-table/': async ({ request }) => {
                    requestBody = (await request.json()) as Record<string, unknown>
                    return [201, makePublication('pending')]
                },
            },
        })
        initKeaTests()
        logic = publishedTablesLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPublishedTablesSuccess'])

        await expectLogic(logic, () => logic.actions.openPublishModal()).toDispatchActions([
            'loadWarehouseTablesSuccess',
        ])
        logic.actions.setPublishTableValues({
            sourceSchemaName: 'analytics',
            sourceTableName: 'customers',
            name: 'customers_snapshot',
        })

        await expectLogic(logic, () => logic.actions.submitPublishTable())
            .toDispatchActions(['closePublishModal', 'loadPublishedTables', 'submitPublishTableSuccess'])
            .toFinishAllListeners()

        expect(requestBody).toEqual({
            source_schema_name: 'analytics',
            source_table_name: 'customers',
            name: 'customers_snapshot',
        })
        expect(listCalls).toBe(2)
        expect(logic.values.publishModalOpen).toBe(false)
        expect(logic.values.publishTable).toEqual({ sourceSchemaName: '', sourceTableName: '', name: '' })
    })

    it.each([
        {
            name: 'publish again',
            action: (logicInstance: ReturnType<typeof publishedTablesLogic.build>) =>
                logicInstance.actions.republishTable('5c98d849-1119-4207-bba2-5161b31a4067'),
            successAction: 'republishTableSuccess',
        },
        {
            name: 'unpublish',
            action: (logicInstance: ReturnType<typeof publishedTablesLogic.build>) =>
                logicInstance.actions.unpublishTable('5c98d849-1119-4207-bba2-5161b31a4067'),
            successAction: 'unpublishTableSuccess',
        },
    ])('refreshes the list after $name', async ({ action, successAction }) => {
        let listCalls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-published-tables/': () => {
                    listCalls += 1
                    return [200, { results: [makePublication('completed')] }]
                },
            },
            post: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-republish-table/': [
                    200,
                    makePublication('completed'),
                ],
            },
            delete: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-published-table/': [204],
            },
        })
        initKeaTests()
        logic = publishedTablesLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPublishedTablesSuccess'])

        await expectLogic(logic, () => action(logic)).toDispatchActions([successAction, 'loadPublishedTablesSuccess'])

        expect(listCalls).toBe(2)
        expect(logic.values.activeMutationId).toBeNull()
    })

    it('polls while a publication is active and stops after it finishes', async () => {
        jest.useFakeTimers()
        let status: PublishedTableApi['status'] = 'pending'
        let listCalls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-published-tables/': () => {
                    listCalls += 1
                    return [200, { results: [makePublication(status)] }]
                },
            },
        })
        initKeaTests()
        logic = publishedTablesLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPublishedTablesSuccess'])

        await jest.advanceTimersByTimeAsync(5000)
        expect(listCalls).toBe(2)

        status = 'completed'
        await jest.advanceTimersByTimeAsync(5000)
        expect(listCalls).toBe(3)
        expect(logic.values.hasActivePublications).toBe(false)

        await jest.advanceTimersByTimeAsync(15000)
        expect(listCalls).toBe(3)
    })

    it('filters publications by their PostHog name and modeled source', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-published-tables/': [
                    200,
                    { results: [makePublication('completed')] },
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
