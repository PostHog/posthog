import { type QueryFrames, afterRequestChange, carryOverResults } from './useQueryFrames'

const lastWeek: QueryFrames = { status: 'ready', refreshing: false, frames: [{ name: 'week', fields: [] }] }
const lastMonth: QueryFrames = { status: 'ready', refreshing: false, frames: [{ name: 'month', fields: [] }] }

describe('afterRequestChange', () => {
    it.each([
        {
            name: 'keeps the last result, marked as refreshing, while an uncached request runs',
            previous: lastWeek,
            cached: { status: 'loading' } as QueryFrames,
            expected: { ...lastWeek, refreshing: true },
        },
        {
            name: 'shows a cached result straight away, without the refreshing mark',
            previous: { ...lastWeek, refreshing: true },
            cached: lastMonth,
            expected: lastMonth,
        },
        {
            name: 'shows loading when there is no earlier result to keep',
            previous: { status: 'error', message: 'timed out' } as QueryFrames,
            cached: { status: 'loading' } as QueryFrames,
            expected: { status: 'loading' },
        },
    ])('$name', ({ previous, cached, expected }) => {
        expect(afterRequestChange(previous, cached)).toEqual(expected)
    })
})

describe('carryOverResults', () => {
    const loading = (): QueryFrames => ({ status: 'loading' })

    it.each([
        {
            name: 'keeps a still-loading query loading when the answered query before it is removed',
            previousKeys: ['a', 'b'],
            previous: [lastWeek, { status: 'loading' } as QueryFrames],
            keys: ['b'],
            expected: [{ status: 'loading' }],
        },
        {
            name: "keeps an edited query's result at its position, marked as refreshing",
            previousKeys: ['a', 'b'],
            previous: [lastWeek, lastMonth],
            keys: ['a', 'b-edited'],
            expected: [
                { ...lastWeek, refreshing: true },
                { ...lastMonth, refreshing: true },
            ],
        },
    ])('$name', ({ previousKeys, previous, keys, expected }) => {
        expect(carryOverResults(previousKeys, previous, keys, loading)).toEqual(expected)
    })
})
