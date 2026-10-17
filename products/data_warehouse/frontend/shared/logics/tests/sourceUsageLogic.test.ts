import { expectLogic } from 'kea-test-utils'

import api, { PaginatedResponse } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { billingLogic } from 'scenes/billing/billingLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingType, ExternalDataSource } from '~/types'

import { dataWarehouseTotalRowsStatsRetrieve } from 'products/data_warehouse/frontend/generated/api'

import { sourcesDataLogic } from '../sourcesDataLogic'
import { sourceUsageLogic } from '../sourceUsageLogic'

jest.mock('lib/api')
jest.mock('products/data_warehouse/frontend/generated/api')

const MANAGED_SOURCE = { id: 's1', source_type: 'Stripe', access_method: 'warehouse', schemas: [] }

const BILLING_WITH_WAREHOUSE = {
    products: [
        {
            type: 'data_warehouse',
            current_amount_usd: '100.00',
            current_amount_usd_before_addons: null,
            current_usage: 1000,
        },
    ],
} as unknown as BillingType

const BILLING_WITHOUT_WAREHOUSE = { products: [] } as unknown as BillingType

describe('sourceUsageLogic', () => {
    let logic: ReturnType<typeof sourceUsageLogic.build>
    let billingResponse: BillingType = BILLING_WITH_WAREHOUSE

    const mountWithBilling = (billing: BillingType): void => {
        billingResponse = billing
        logic = sourceUsageLogic()
        logic.mount()
    }

    beforeEach(() => {
        initKeaTests()
        useMocks({ get: { '/api/billing/': () => [200, billingResponse] } })
        jest.spyOn(api.externalDataSources, 'list').mockResolvedValue({
            results: [],
            count: 0,
            next: null,
            previous: null,
        } as PaginatedResponse<ExternalDataSource>)
        ;(dataWarehouseTotalRowsStatsRetrieve as jest.Mock).mockResolvedValue(null)
    })

    afterEach(() => {
        logic?.unmount()
    })

    const loadSources = (sources: (typeof MANAGED_SOURCE)[]): void => {
        sourcesDataLogic.actions.loadSourcesSuccess({
            results: sources,
            count: sources.length,
            next: null,
            previous: null,
        } as unknown as PaginatedResponse<ExternalDataSource>)
    }

    test.each([
        { variant: 'test', sources: [MANAGED_SOURCE], billing: BILLING_WITH_WAREHOUSE, loads: true },
        { variant: 'control', sources: [MANAGED_SOURCE], billing: BILLING_WITH_WAREHOUSE, loads: false },
        { variant: 'test', sources: [], billing: BILLING_WITH_WAREHOUSE, loads: false },
        { variant: 'test', sources: [MANAGED_SOURCE], billing: BILLING_WITHOUT_WAREHOUSE, loads: false },
    ])(
        'loads usage once, only for the test variant with a source and a billing product (%o)',
        async ({ variant, sources, billing, loads }) => {
            mountWithBilling(billing)
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DWH_SOURCE_COST_COLUMNS]: variant })
            loadSources(sources)
            if (sources.length > 0) {
                await expectLogic(billingLogic).toDispatchActions(['loadBillingSuccess'])
            }
            await expectLogic(logic).toFinishListeners()
            loadSources(sources)
            await expectLogic(logic).toFinishListeners()

            await expectLogic(logic).toMatchValues({ showUsageColumns: loads })
            expect((dataWarehouseTotalRowsStatsRetrieve as jest.Mock).mock.calls.length).toBe(loads ? 1 : 0)
        }
    )

    test.each([
        {
            billingAvailable: true,
            expected: { s1: { billableRows: 300, costUsd: 30 } },
        },
        { billingAvailable: false, expected: null },
    ])('turns the stats response into per-source usage (%o)', async ({ billingAvailable, expected }) => {
        ;(dataWarehouseTotalRowsStatsRetrieve as jest.Mock).mockResolvedValue({
            billing_available: billingAvailable,
            billable_rows_by_source: { s1: 300 },
        })
        mountWithBilling(BILLING_WITH_WAREHOUSE)
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DWH_SOURCE_COST_COLUMNS]: 'test' })
        loadSources([MANAGED_SOURCE])

        await expectLogic(logic)
            .toDispatchActions(['loadRowsStatsSuccess'])
            .toMatchValues({ sourceUsageById: expected })
    })
})
