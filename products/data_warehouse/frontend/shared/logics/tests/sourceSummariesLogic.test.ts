import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import type {
    ExternalDataSourceSummaryApi,
    PaginatedExternalDataSourceSummaryListApi,
} from 'products/warehouse_sources/frontend/generated/api.schemas'

import {
    areSourceSummariesActivelySyncing,
    shouldLoadSourceSummaries,
    sourceSummariesLogic,
} from '../sourceSummariesLogic'

jest.mock('lib/api')

const sourceSummary = (overrides: Partial<ExternalDataSourceSummaryApi> = {}): ExternalDataSourceSummaryApi => ({
    id: 'source-1',
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    created_via: 'web',
    status: 'Completed',
    source_type: 'Postgres',
    latest_error: null,
    prefix: 'prod',
    description: null,
    access_method: 'warehouse',
    direct_query_enabled: false,
    engine: 'postgres',
    last_run_at: null,
    revenue_analytics_config: { enabled: false, include_invoiceless_charges: true },
    user_access_level: 'editor',
    schemas_count: 1,
    rows_synced: 10,
    schema_status_names: { Completed: ['Customers'] },
    ...overrides,
})

describe('sourceSummariesLogic', () => {
    let logic: ReturnType<typeof sourceSummariesLogic.build>

    beforeEach(() => {
        initKeaTests()
        router.actions.push('/project/997/data-management/sources')
        jest.spyOn(api.externalDataSources, 'wizard').mockResolvedValue({})
        logic = sourceSummariesLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads only source summaries', async () => {
        const response: PaginatedExternalDataSourceSummaryListApi = {
            results: [sourceSummary()],
            count: 1,
            next: null,
            previous: null,
        }
        jest.spyOn(api.externalDataSources, 'listSummaries').mockResolvedValue(response)

        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadSourceSummariesSuccess']).toMatchValues({
            sourceSummaries: response,
            sourceSummariesLoading: false,
        })
        expect(api.externalDataSources.listSummaries).toHaveBeenCalledWith({ signal: expect.any(AbortSignal) })
        expect(api.externalDataSources.list).not.toHaveBeenCalled()
    })

    it('separates and searches managed and direct sources', async () => {
        jest.mocked(api.externalDataSources.wizard).mockResolvedValue({
            GoogleAds: { name: 'GoogleAds', label: 'Google Ads' },
        } as any)
        jest.spyOn(api.externalDataSources, 'listSummaries').mockResolvedValue({
            results: [
                sourceSummary({ source_type: 'GoogleAds' }),
                sourceSummary({ id: 'source-2', access_method: 'direct', prefix: 'analytics' }),
            ],
            count: 2,
            next: null,
            previous: null,
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSourceSummariesSuccess'])

        logic.actions.setManagedSearchTerm('Google ads')
        logic.actions.setDirectSearchTerm('analytics')

        await expectLogic(logic).toMatchValues({
            filteredManagedSourceSummaries: [expect.objectContaining({ id: 'source-1' })],
            filteredDirectSourceSummaries: [expect.objectContaining({ id: 'source-2' })],
        })
    })

    it('detects running schemas and recognizes summary-backed routes', () => {
        expect(
            areSourceSummariesActivelySyncing({
                results: [sourceSummary({ status: 'Failed', schema_status_names: { Running: ['Customers'] } })],
                count: 1,
                next: null,
                previous: null,
            })
        ).toBe(true)
        expect(shouldLoadSourceSummaries('/project/997/data-management/sources')).toBe(true)
        expect(shouldLoadSourceSummaries('/project/997/data-management/revenue')).toBe(true)
        expect(shouldLoadSourceSummaries('/project/997/sql')).toBe(false)
    })
})
