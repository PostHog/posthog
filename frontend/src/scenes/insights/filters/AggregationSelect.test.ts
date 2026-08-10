import { isCustomHogQLAggregation } from './AggregationSelect'

describe('isCustomHogQLAggregation', () => {
    // Guards the funnel warning banner: it must fire for custom SQL expressions
    // (whose value only lives on some step events) and stay silent for the
    // standard person / group / session options that all events carry.
    test.each([
        [undefined, false],
        [null, false],
        ['', false],
        ['person_id', false],
        ['properties.$session_id', false],
        ['$group_0', false],
        ['$group_12', false],
        ['properties.payment_id', true],
        ['distinct_id', true],
        ["concat(distinct_id, ' ', properties.$session_id)", true],
    ])('isCustomHogQLAggregation(%p) === %p', (value, expected) => {
        expect(isCustomHogQLAggregation(value as string | null | undefined)).toBe(expected)
    })
})
