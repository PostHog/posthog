import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { billingReadsLogic } from './billingReads'

describe('billingReadsLogic', () => {
    const SERIES = { start_date: '2026-08-01', end_date: '2026-08-31', breakdowns: '["type"]' }

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/organizations/@current/billing/projects/': () => [
                    200,
                    { results: [{ id: 7, name: null, deleted: true }] },
                ],
                '/api/billing/usage/team_options/': () => [200, { team_id_options: [7, 8] }],
            },
        })
        featureFlagLogic.mount()
        billingReadsLogic.mount()
    })

    it.each([
        {
            flag: true,
            usageSeries: '/api/organizations/@current/billing/usage/timeseries/',
            spendSeries: '/api/organizations/@current/billing/spend/timeseries/',
            usageExport: '/api/organizations/@current/billing/usage/export/',
            spendExport: '/api/organizations/@current/billing/spend/export/',
            projectIds: [7],
        },
        {
            flag: false,
            usageSeries: 'api/billing/usage/',
            spendSeries: 'api/billing/spend/',
            usageExport: '/api/billing/usage/export/',
            spendExport: '/api/billing/spend/export/',
            projectIds: [7, 8],
        },
    ])('reads from the routes the flag selects (flag on: $flag)', async (expected) => {
        featureFlagLogic.actions.setFeatureFlags(expected.flag ? [FEATURE_FLAGS.ORGANIZATION_BILLING_API] : [], {
            [FEATURE_FLAGS.ORGANIZATION_BILLING_API]: expected.flag,
        })
        const reads = billingReadsLogic.values.billingReads

        expect(reads.usageSeriesUrl(SERIES).split('?')[0]).toEqual(expected.usageSeries)
        expect(reads.spendSeriesUrl(SERIES).split('?')[0]).toEqual(expected.spendSeries)
        expect(reads.usageExportUrl(SERIES).split('?')[0]).toEqual(expected.usageExport)
        expect(reads.spendExportUrl(SERIES).split('?')[0]).toEqual(expected.spendExport)
        expect(reads.usageSeriesUrl(SERIES)).toContain('breakdowns=')
        expect(await reads.reportedProjectIds()).toEqual(expected.projectIds)
    })
})
