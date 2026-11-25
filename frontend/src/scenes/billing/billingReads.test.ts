import { MOCK_ORGANIZATION_ID } from 'lib/api.mock'

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
                [`/api/organizations/${MOCK_ORGANIZATION_ID}/billing/projects/`]: () => [
                    200,
                    { results: [{ id: 7, name: null, deleted: true }] },
                ],
                '/api/billing/usage/team_options/': ({ request }) => [
                    200,
                    {
                        team_id_options:
                            new URL(request.url).searchParams.get('organization_id') === MOCK_ORGANIZATION_ID
                                ? [7, 8]
                                : [],
                    },
                ],
                [`/api/organizations/${MOCK_ORGANIZATION_ID}/billing/usage/timeseries/`]: ({ request }) => [
                    200,
                    {
                        count: 1,
                        next: null,
                        previous: null,
                        results: [point(`organization usage ${new URL(request.url).searchParams.get('breakdowns')}`)],
                    },
                ],
                [`/api/organizations/${MOCK_ORGANIZATION_ID}/billing/spend/timeseries/`]: () => [
                    200,
                    {
                        count: 1,
                        next: null,
                        previous: null,
                        results: [point('organization spend')],
                        pricing_reset_dates: ['2026-08-19'],
                    },
                ],
                '/api/billing/usage/': ({ request }) => {
                    const searchParams = new URL(request.url).searchParams
                    return [
                        200,
                        {
                            results: [
                                point(
                                    `legacy usage ${searchParams.get('breakdowns')} for ${searchParams.get('organization_id')}`
                                ),
                            ],
                        },
                    ]
                },
                '/api/billing/spend/': ({ request }) => [
                    200,
                    {
                        results: [
                            point(`legacy spend for ${new URL(request.url).searchParams.get('organization_id')}`),
                        ],
                        pricing_reset_dates: ['2026-08-19'],
                    },
                ],
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
            usageExport: `/api/organizations/${MOCK_ORGANIZATION_ID}/billing/usage/export/`,
            spendExport: `/api/organizations/${MOCK_ORGANIZATION_ID}/billing/spend/export/`,
            exportOrganizationParam: null,
            projectIds: [7],
        },
        {
            flag: false,
            usageLabel: `legacy usage ["type"] for ${MOCK_ORGANIZATION_ID}`,
            spendLabel: `legacy spend for ${MOCK_ORGANIZATION_ID}`,
            usageExport: '/api/billing/usage/export/',
            spendExport: '/api/billing/spend/export/',
            exportOrganizationParam: MOCK_ORGANIZATION_ID,
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
        const spend = await reads.spendSeries(SERIES)
        expect(spend.results[0].label).toEqual(expected.spendLabel)
        expect(spend).toHaveProperty('pricing_reset_dates', ['2026-08-19'])
        const usageExportUrl = new URL(reads.usageExportUrl(SERIES), 'http://localhost')
        const spendExportUrl = new URL(reads.spendExportUrl(SERIES), 'http://localhost')
        expect(usageExportUrl.pathname).toEqual(expected.usageExport)
        expect(spendExportUrl.pathname).toEqual(expected.spendExport)
        expect(usageExportUrl.searchParams.get('organization_id')).toEqual(expected.exportOrganizationParam)
        expect(spendExportUrl.searchParams.get('organization_id')).toEqual(expected.exportOrganizationParam)
        expect(await reads.reportedProjectIds()).toEqual(expected.projectIds)
    })
})
