import { type QueryFrames, afterRequestChange, carryOverResults, withShownFrames } from './useQueryFrames'

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

describe('withShownFrames', () => {
    const ready = (hash?: string): Extract<QueryFrames, { status: 'ready' }> => ({
        status: 'ready',
        refreshing: false,
        frames: [{ hash, fields: [] }],
    })

    it.each([
        { name: 'keeps the shown frames when a refresh returns the same hashes', shown: 'a', next: 'a', kept: true },
        { name: 'takes the new frames when their content changed', shown: 'a', next: 'b', kept: false },
        { name: 'takes the new frames when the runner sends no hash', shown: undefined, next: undefined, kept: false },
    ])('$name', ({ shown, next, kept }) => {
        const previous = ready(shown)
        const fresh = ready(next)
        const result = withShownFrames(previous, fresh)

        expect(result.status === 'ready' && result.frames).toBe(kept ? previous.frames : fresh.frames)
    })
})
