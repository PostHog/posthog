import { expectLogic } from 'kea-test-utils'

import api, { PaginatedResponse } from 'lib/api'

import { initKeaTests } from '~/test/init'
import { DataWarehouseActivityRecord, DataWarehouseSyncInterval, ExternalDataSource } from '~/types'

import { externalDataSourcesLogic } from './externalDataSourcesLogic'

jest.mock('lib/api')

describe('externalDataSourcesLogic', () => {
    let logic: ReturnType<typeof externalDataSourcesLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = externalDataSourcesLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads external data sources from centralized api call', async () => {
        const mockResponse: PaginatedResponse<ExternalDataSource> = {
            results: [
                {
                    id: 'test-1',
                    source_id: 'source-1',
                    connection_id: 'conn-1',
                    source_type: 'Postgres',
                    status: 'Running',
                    schemas: [],
                    prefix: 'test',
                    latest_error: null,
                    revenue_analytics_enabled: false,
                    sync_frequency: '24hour' as DataWarehouseSyncInterval,
                    job_inputs: {},
                },
            ],
            next: null,
            previous: null,
        }

        jest.spyOn(api.externalDataSources, 'list').mockResolvedValue(mockResponse)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadSources(null)
        })
            .toDispatchActions(['loadSources', 'loadSourcesSuccess'])
            .toMatchValues({
                dataWarehouseSources: mockResponse,
                dataWarehouseSourcesLoading: false,
            })

        expect(api.externalDataSources.list).toHaveBeenCalledWith({ signal: expect.any(AbortSignal) })
    })

    describe('pagination functionality', () => {
        it('calculates pagination state correctly', () => {
            const mockActivity: DataWarehouseActivityRecord[] = Array.from({ length: 12 }, (_, i) => ({
                id: `activity-${i}`,
                name: `Activity ${i}`,
                type: 'test',
                status: 'completed',
                created_at: '2023-01-01T00:00:00Z',
                finished_at: '2023-01-01T00:00:00Z',
                latest_error: null,
                rows: 100,
            }))

            logic.mount()
            logic.actions.setRecentActivityData(mockActivity, false)

            expect(logic.values.activityPaginationState).toMatchObject({
                currentPage: 1,
                pageCount: 3, // 12 items / 5 per page = 2.4, rounded up to 3
                entryCount: 12,
                currentStartIndex: 0,
                currentEndIndex: 5,
                dataSourcePage: mockActivity.slice(0, 5),
                isOnLastPage: false,
                hasDataOnCurrentPage: true,
            })
        })

        it('updates current page correctly', () => {
            const mockActivity: DataWarehouseActivityRecord[] = Array.from({ length: 12 }, (_, i) => ({
                id: `activity-${i}`,
                name: `Activity ${i}`,
                type: 'test',
                status: 'completed',
                created_at: '2023-01-01T00:00:00Z',
                finished_at: '2023-01-01T00:00:00Z',
                latest_error: null,
                rows: 100,
            }))

            logic.mount()
            logic.actions.setRecentActivityData(mockActivity, false)
            logic.actions.setActivityCurrentPage(2)

            expect(logic.values.activityPaginationState).toMatchObject({
                currentPage: 2,
                currentStartIndex: 5,
                currentEndIndex: 10,
                dataSourcePage: mockActivity.slice(5, 10),
                isOnLastPage: false,
                hasDataOnCurrentPage: true,
            })
        })
    })
})
