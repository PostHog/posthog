import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api, { ApiError, PaginatedResponse } from 'lib/api'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DataWarehouseSyncInterval, ExternalDataJobStatus, ExternalDataSource } from '~/types'

import type { PaginatedExternalDataSourceSummaryListApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { shouldLoadSourceSummaries, sourcesDataLogic } from '../sourcesDataLogic'

// Stub the default `api` export but keep the real ApiError class so both the
// test fixtures and the loader reference the same constructor — the loader's
// `error instanceof ApiError` guard would otherwise never match an auto-mocked
// ApiError instance.
jest.mock('lib/api', () => {
    const actual = jest.requireActual('lib/api')
    return {
        __esModule: true,
        ...actual,
        default: {
            externalDataSources: {
                list: jest.fn(),
                listSummaries: jest.fn(),
                update: jest.fn(),
                updateRevenueAnalyticsConfig: jest.fn(),
            },
        },
    }
})

const emptyResponse: PaginatedResponse<ExternalDataSource> = {
    results: [],
    count: 0,
    next: null,
    previous: null,
} as PaginatedResponse<ExternalDataSource>

const emptySummaryResponse: PaginatedExternalDataSourceSummaryListApi = {
    results: [],
    count: 0,
    next: null,
    previous: null,
}

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

        jest.spyOn(api.externalDataSources, 'list').mockResolvedValue(mockResponse)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadSources()
        })
            .toDispatchActions(['loadSources', 'loadSourcesSuccess'])
            .toMatchValues({
                dataWarehouseSources: mockResponse,
                dataWarehouseSourcesLoading: false,
            })

        expect(api.externalDataSources.list).toHaveBeenCalledWith({ signal: expect.any(AbortSignal) })
    })

    it('loads source summaries only on the sources list page', async () => {
        expect(shouldLoadSourceSummaries('/data-management/sources')).toBe(true)
        expect(shouldLoadSourceSummaries('/project/997/data-management/sources')).toBe(true)
        expect(shouldLoadSourceSummaries('/data-management/revenue')).toBe(false)

        jest.spyOn(api.externalDataSources, 'listSummaries').mockResolvedValue(emptySummaryResponse)
        jest.spyOn(api.externalDataSources, 'list').mockResolvedValue(emptyResponse)

        logic.mount()
        router.actions.push('/project/997/data-management/sources')
        await expectLogic(logic, () => logic.actions.loadSources()).toDispatchActions(['loadSourcesSuccess'])

        expect(api.externalDataSources.listSummaries).toHaveBeenCalledWith({ signal: expect.any(AbortSignal) })
        expect(api.externalDataSources.list).not.toHaveBeenCalled()
    })

    it.each([
        ['403 access denied', new ApiError('forbidden', 403)],
        ['network failure (no HTTP status)', new ApiError('TypeError: Failed to fetch', undefined)],
        ['aborted request', Object.assign(new Error('aborted'), { name: 'AbortError' })],
    ])('returns an empty paginated result on %s without surfacing loader failure', async (_label, error) => {
        jest.spyOn(api.externalDataSources, 'list').mockRejectedValue(error)

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
