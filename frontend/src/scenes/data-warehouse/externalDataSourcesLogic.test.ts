import { expectLogic } from 'kea-test-utils'

import api, { PaginatedResponse } from 'lib/api'

import { initKeaTests } from '~/test/init'
import { DataWarehouseSyncInterval, ExternalDataSource } from '~/types'

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
                    revenue_analytics_config: {
                        enabled: false,
                        include_invoiceless_charges: true,
                    },
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
})
