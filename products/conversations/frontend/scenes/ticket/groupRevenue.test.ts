import { GroupRevenue, GroupRevenueAnalyticsRow, resolveGroupRevenue } from './groupRevenue'

describe('resolveGroupRevenue', () => {
    it.each<[string, GroupRevenueAnalyticsRow | undefined, Record<string, any> | undefined, GroupRevenue]>([
        [
            'revenue analytics wins over group properties',
            { mrr: 100, lifetimeValue: 2000 },
            { mrr: 5, customer_lifetime_value: 50 },
            {
                mrr: { value: 100, source: 'revenue-analytics' },
                lifetimeValue: { value: 2000, source: 'revenue-analytics' },
            },
        ],
        [
            'a zero from revenue analytics is a value, not a gap',
            { mrr: 0, lifetimeValue: 2000 },
            { mrr: 5 },
            {
                mrr: { value: 0, source: 'revenue-analytics' },
                lifetimeValue: { value: 2000, source: 'revenue-analytics' },
            },
        ],
        [
            'falls back to group properties per field',
            { mrr: null, lifetimeValue: 2000 },
            { mrr: 5, customer_lifetime_value: 50 },
            {
                mrr: { value: 5, source: 'properties' },
                lifetimeValue: { value: 2000, source: 'revenue-analytics' },
            },
        ],
        [
            'no revenue analytics row',
            undefined,
            { mrr: 5, customer_lifetime_value: 50 },
            {
                mrr: { value: 5, source: 'properties' },
                lifetimeValue: { value: 50, source: 'properties' },
            },
        ],
        [
            'non-numeric group properties are ignored',
            undefined,
            { mrr: '5', customer_lifetime_value: NaN },
            {
                mrr: { value: null, source: null },
                lifetimeValue: { value: null, source: null },
            },
        ],
        [
            'no data at all',
            undefined,
            undefined,
            {
                mrr: { value: null, source: null },
                lifetimeValue: { value: null, source: null },
            },
        ],
    ])('%s', (_label, analyticsRow, groupProperties, expected) => {
        expect(resolveGroupRevenue(analyticsRow, groupProperties)).toEqual(expected)
    })
})
