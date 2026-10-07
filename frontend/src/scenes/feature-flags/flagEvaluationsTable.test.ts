import { insightReachesPastFlagEvaluationsRetention } from './flagEvaluationsTable'

describe('flagEvaluationsTable', () => {
    it.each([
        ['a range inside the window', { date_from: '-30d' }, undefined, false],
        ['a range past the window', { date_from: '-180d' }, undefined, true],
        ['all time', { date_from: 'all' }, undefined, true],
        ['a missing start, which the runners read as the last 7 days', undefined, undefined, false],
        ['a previous period inside the window', { date_from: '-30d' }, { compare: true }, false],
        [
            'a previous period that doubles the range back past the window',
            { date_from: '-60d' },
            { compare: true },
            true,
        ],
        ['a comparison shifted inside the window', { date_from: '-30d' }, { compare: true, compare_to: '-30d' }, false],
        ['a comparison shifted past the window', { date_from: '-30d' }, { compare: true, compare_to: '-1y' }, true],
    ])('insightReachesPastFlagEvaluationsRetention: %s', (_name, dateRange, compareFilter, expected) => {
        expect(insightReachesPastFlagEvaluationsRetention(dateRange, compareFilter)).toBe(expected)
    })
})
