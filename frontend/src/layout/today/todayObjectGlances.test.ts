import { CurrencyCode } from '~/queries/schema/schema-general'

import type { InsightApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { flagRollout, insightGlance } from './todayObjectGlances'

describe('todayObjectGlances', () => {
    const aggregationLabel = (index: number | null | undefined): { singular: string; plural: string } =>
        index == null ? { singular: 'user', plural: 'users' } : { singular: 'organization', plural: 'organizations' }

    test.each([
        ['variants win', { multivariate: { variants: [{}, {}] }, groups: [{ rollout_percentage: 100 }] }, '2 variants'],
        ['one open group', { groups: [{ properties: [], rollout_percentage: 25 }] }, '25% of users'],
        ['one group with no percentage', { groups: [{ properties: [] }] }, '100% of users'],
        [
            'one open group of organizations',
            { aggregation_group_type_index: 0, groups: [{ properties: [], rollout_percentage: 25 }] },
            '25% of organizations',
        ],
        ['targeted groups', { groups: [{ properties: [{}] }, { properties: [] }] }, '2 release conditions'],
        ['rules v2', { version: 2, return_type: 'boolean', rules: [{}, {}, {}] }, '3 rules'],
        ['an unsupported version', { version: 9 }, null],
    ])('rollout: %s', (_name, filters, expected) => {
        expect(flagRollout(filters, aggregationLabel)?.replace(/\s/g, ' ') ?? null).toBe(expected)
    })

    test.each([
        [
            'trend',
            [{ label: 'Pageview', count: 1208, data: [3, 5, 1200], labels: ['a', 'b', 'c'] }],
            null,
            '1.2k',
            'Pageview',
        ],
        [
            'single-bucket trends',
            [
                { label: 'Signed up', count: 100, data: [100] },
                { count: 25, data: [25] },
            ],
            null,
            '100',
            'Signed up',
        ],
        [
            'trend in scaled percent',
            [{ label: 'Rate', data: [0.5, 0.0123456] }],
            {
                kind: 'InsightVizNode',
                source: {
                    kind: 'TrendsQuery',
                    series: [],
                    trendsFilter: { aggregationAxisFormat: 'percentage_scaled' },
                },
            },
            '1.23%',
            'Rate',
        ],
        ['funnel', [{ count: 200 }, { count: 50 }], null, '25%', 'conversion'],
        [
            'compared funnel',
            [
                { count: 200, compare_label: 'current' },
                { count: 100, compare_label: 'current' },
                { count: 150, compare_label: 'previous' },
                { count: 60, compare_label: 'previous' },
            ],
            null,
            '50%',
            'conversion',
        ],
        ['breakdown funnel', [[{ count: 10 }, { count: 4 }]], null, '40%', 'conversion'],
        ['no cached result', null, null, undefined, undefined],
    ])('headline: %s', (_name, result, query, value, caption) => {
        const { headline } = insightGlance(
            { result, query, description: '' } as unknown as InsightApi,
            CurrencyCode.USD
        )
        expect([headline?.value, headline?.caption]).toEqual([value, caption])
    })
})
