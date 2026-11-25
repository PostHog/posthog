import { type QueryFrames, afterRequestChange } from './useQueryFrames'

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
