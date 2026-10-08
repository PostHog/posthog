import { expectLogic } from 'kea-test-utils'

import api, { PaginatedResponse } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { ExternalDataSource } from '~/types'

import { dataWarehouseTotalRowsStatsRetrieve } from 'products/data_warehouse/frontend/generated/api'

import { sourcesDataLogic } from '../sourcesDataLogic'
import { sourceUsageLogic } from '../sourceUsageLogic'

jest.mock('lib/api')
jest.mock('products/data_warehouse/frontend/generated/api')

const MANAGED_SOURCE = { id: 's1', source_type: 'Stripe', access_method: 'warehouse', schemas: [] }

describe('sourceUsageLogic', () => {
    let logic: ReturnType<typeof sourceUsageLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.externalDataSources, 'list').mockResolvedValue({
            results: [],
            count: 0,
            next: null,
            previous: null,
        } as PaginatedResponse<ExternalDataSource>)
        ;(dataWarehouseTotalRowsStatsRetrieve as jest.Mock).mockResolvedValue(null)
        logic = sourceUsageLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    test.each([
        { variant: 'test', sources: [MANAGED_SOURCE], loads: true },
        { variant: 'control', sources: [MANAGED_SOURCE], loads: false },
        { variant: 'test', sources: [], loads: false },
    ])('loads usage only for the test variant with a source (%o)', async ({ variant, sources, loads }) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DWH_SOURCE_COST_COLUMNS]: variant })
        sourcesDataLogic.actions.loadSourcesSuccess({
            results: sources,
            count: sources.length,
            next: null,
            previous: null,
        } as unknown as PaginatedResponse<ExternalDataSource>)

        await expectLogic(logic).toMatchValues({ showUsageColumns: loads })
        expect((dataWarehouseTotalRowsStatsRetrieve as jest.Mock).mock.calls.length > 0).toBe(loads)
    })
})
