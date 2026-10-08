import { estimateSourceCostsUsd } from './sourceUsageCost'

describe('estimateSourceCostsUsd', () => {
    test.each([
        {
            name: 'splits the organization amount by share of organization rows',
            rows: { a: 300, b: 100 },
            product: { current_amount_usd: '100.00', current_usage: 1000 },
            expected: { a: 30, b: 10 },
        },
        {
            name: 'uses project rows when billing has not counted them yet',
            rows: { a: 300, b: 100 },
            product: { current_amount_usd: '40.00', current_usage: 200 },
            expected: { a: 30, b: 10 },
        },
        {
            name: 'returns zero for every source when nothing was billed',
            rows: { a: 0 },
            product: { current_amount_usd: '0.00', current_usage: 0 },
            expected: { a: 0 },
        },
        {
            name: 'returns null without a billed amount',
            rows: { a: 300 },
            product: { current_amount_usd: null, current_usage: 300 },
            expected: null,
        },
        {
            name: 'returns null without the billing product',
            rows: { a: 300 },
            product: undefined,
            expected: null,
        },
    ])('$name', ({ rows, product, expected }) => {
        expect(estimateSourceCostsUsd(rows, product)).toEqual(expected)
    })
})
