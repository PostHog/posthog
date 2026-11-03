import { aggregateDotMatrixMockPeople, getDotMatrixMockDataset, type DotMatrixMockDatum } from './mocks'

const person = { id: 'one', name: 'alex', email: 'alex@example.com', seconds: 60 }

function datum(seriesKey: string, value: number): DotMatrixMockDatum {
    return { rowKey: 'account', columnKey: 'week', seriesKey, value, persons: [person] }
}

describe('dot matrix mock aggregation', () => {
    test.each([
        { data: [datum('first', 0)], selected: ['first'], expected: 0 },
        { data: [datum('first', 1), datum('second', 1)], selected: ['first', 'second'], expected: 1 },
        { data: [datum('first', 1), datum('second', 1)], selected: ['absent'], expected: 0 },
    ])('counts active distinct people in the selection: $expected', ({ data, selected, expected }) => {
        expect(aggregateDotMatrixMockPeople({ rowKey: 'account', columnKey: 'week', data, values: {} }, selected)).toBe(
            expected
        )
    })

    it('counts selected failing CI jobs without person records', () => {
        const dataset = getDotMatrixMockDataset('ci')
        expect(
            dataset.aggregateSelection?.(
                { rowKey: 'repo', columnKey: 'week', data: [], values: { build: 5, lint: 0, deploy: 3 } },
                ['build', 'lint']
            )
        ).toBe(1)
    })
})
