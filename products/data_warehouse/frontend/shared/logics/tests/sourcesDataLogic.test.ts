import { expectLogic } from 'kea-test-utils'

import { ApiError, PaginatedResponse } from 'lib/api'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DataWarehouseSyncInterval, ExternalDataJobStatus, ExternalDataSource } from '~/types'

import { generatedExternalDataSources } from 'products/warehouse_sources/frontend/warehouseSourcesApi'

import { sourcesDataLogic } from '../sourcesDataLogic'

const emptyResponse: PaginatedResponse<ExternalDataSource> = {
    results: [],
    count: 0,
    next: null,
    previous: null,
} as PaginatedResponse<ExternalDataSource>

describe('sourcesDataLogic', () => {
    let logic: ReturnType<typeof sourcesDataLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sourcesDataLogic()
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
                    status: ExternalDataJobStatus.Running,
                    schemas: [],
                    prefix: 'test',
                    description: null,
                    created_via: 'web',
                    latest_error: null,
                    revenue_analytics_config: {
                        enabled: false,
                        include_invoiceless_charges: true,
                    },
                    sync_frequency: '24hour' as DataWarehouseSyncInterval,
                    job_inputs: {},
                    user_access_level: AccessControlLevel.Manager,
                },
            ],
            next: null,
            previous: null,
        }

        jest.spyOn(generatedExternalDataSources, 'list').mockResolvedValue(mockResponse)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadSources()
        })
            .toDispatchActions(['loadSources', 'loadSourcesSuccess'])
            .toMatchValues({
                dataWarehouseSources: mockResponse,
                dataWarehouseSourcesLoading: false,
            })

        expect(generatedExternalDataSources.list).toHaveBeenCalledWith({ signal: expect.any(AbortSignal) })
    })

    it.each([
        ['403 access denied', new ApiError('forbidden', 403)],
        ['network failure (no HTTP status)', new ApiError('TypeError: Failed to fetch', undefined)],
        ['aborted request', Object.assign(new Error('aborted'), { name: 'AbortError' })],
    ])('returns an empty paginated result on %s without surfacing loader failure', async (_label, error) => {
        jest.spyOn(generatedExternalDataSources, 'list').mockRejectedValue(error)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadSources()
        })
            .toDispatchActions(['loadSources', 'loadSourcesSuccess'])
            .toNotHaveDispatchedActions(['loadSourcesFailure'])
            .toMatchValues({
                dataWarehouseSources: emptyResponse,
                dataWarehouseSourcesLoading: false,
            })
    })
})
