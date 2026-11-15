import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { billingReadsLogic } from './billingReads'

describe('billingReadsLogic', () => {
    const SERIES = { start_date: '2026-08-01', end_date: '2026-08-31', breakdowns: '["type"]' }
    const point = (label: string): Record<string, unknown> => ({
        id: 1,
        label,
        data: [3],
        dates: ['2026-08-01'],
        breakdown_type: 'type',
    })

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/organizations/@current/billing/projects/': () => [
                    200,
                    { results: [{ id: 7, name: null, deleted: true }] },
                ],
                '/api/billing/usage/team_options/': () => [200, { team_id_options: [7, 8] }],
                '/api/organizations/@current/billing/usage/timeseries/': ({ request }) => [
                    200,
                    {
                        count: 1,
                        next: null,
                        previous: null,
                        results: [point(`organization usage ${new URL(request.url).searchParams.get('breakdowns')}`)],
                    },
                ],
                '/api/organizations/@current/billing/spend/timeseries/': () => [
                    200,
                    { count: 1, next: null, previous: null, results: [point('organization spend')] },
                ],
                '/api/billing/usage/': ({ request }) => [
                    200,
                    { results: [point(`legacy usage ${new URL(request.url).searchParams.get('breakdowns')}`)] },
                ],
                '/api/billing/spend/': () => [200, { results: [point('legacy spend')] }],
            },
        })
        featureFlagLogic.mount()
        billingReadsLogic.mount()
    })

    it.each([
        {
            flag: true,
            usageLabel: 'organization usage ["type"]',
            spendLabel: 'organization spend',
            usageExport: '/api/organizations/@current/billing/usage/export/',
            spendExport: '/api/organizations/@current/billing/spend/export/',
            projectIds: [7],
        },
        {
            flag: false,
            usageLabel: 'legacy usage ["type"]',
            spendLabel: 'legacy spend',
            usageExport: '/api/billing/usage/export/',
            spendExport: '/api/billing/spend/export/',
            projectIds: [7, 8],
        },
    ])('reads from the routes the flag selects (flag on: $flag)', async (expected) => {
        featureFlagLogic.actions.setFeatureFlags(expected.flag ? [FEATURE_FLAGS.ORGANIZATION_BILLING_API] : [], {
            [FEATURE_FLAGS.ORGANIZATION_BILLING_API]: expected.flag,
        })
        const reads = billingReadsLogic.values.billingReads

        const usage = await reads.usageSeries(SERIES)
        expect(usage.results).toEqual([
            {
                id: 1,
                label: expected.usageLabel,
                data: [3],
                dates: ['2026-08-01'],
                breakdown_type: 'type',
                breakdown_value: null,
            },
        ])
        expect((await reads.spendSeries(SERIES)).results[0].label).toEqual(expected.spendLabel)
        expect(reads.usageExportUrl(SERIES).split('?')[0]).toEqual(expected.usageExport)
        expect(reads.spendExportUrl(SERIES).split('?')[0]).toEqual(expected.spendExport)
        expect(await reads.reportedProjectIds()).toEqual(expected.projectIds)
    })
})
