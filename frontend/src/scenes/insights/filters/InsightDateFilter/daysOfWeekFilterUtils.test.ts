import { TrendsQuery } from '~/queries/schema/schema-general'

import { computeDaysOfWeekUpdate, daysOfWeekLabel, getEffectiveDaysOfWeek } from './daysOfWeekFilterUtils'

describe('daysOfWeekFilterUtils', () => {
    it.each([
        ['daysOfWeek set', { daysOfWeek: [2, 1] }, undefined, [1, 2]],
        ['legacy hideWeekends reads as weekdays', {}, { hideWeekends: true }, [1, 2, 3, 4, 5]],
        ['daysOfWeek wins over hideWeekends', { daysOfWeek: [6, 7] }, { hideWeekends: true }, [6, 7]],
        ['neither set means all days', {}, {}, []],
    ])('getEffectiveDaysOfWeek: %s', (_name, dateRange, trendsFilter, expected) => {
        expect(getEffectiveDaysOfWeek(dateRange, trendsFilter)).toEqual(expected)
    })

    it.each([
        [[], 'All days'],
        [[1, 2, 3, 4, 5, 6, 7], 'All days'],
        [[1, 2, 3, 4, 5], 'Weekdays'],
        [[6, 7], 'Weekends'],
        [[1, 3], 'Mon, Wed'],
    ])('daysOfWeekLabel(%p) is %s', (days, expected) => {
        expect(daysOfWeekLabel(days)).toBe(expected)
    })

    it.each<[string, number[], Partial<TrendsQuery> | null, object, object]>([
        ['empty selection normalises to null daysOfWeek', [], null, {}, { dateRange: { daysOfWeek: null } }],
        [
            'all 7 days normalises to null daysOfWeek',
            [1, 2, 3, 4, 5, 6, 7],
            null,
            {},
            { dateRange: { daysOfWeek: null } },
        ],
        ['partial selection is sorted', [5, 1, 3], null, {}, { dateRange: { daysOfWeek: [1, 3, 5] } }],
        [
            'clears legacy hideWeekends when it was set',
            [1, 2, 3],
            { kind: 'TrendsQuery', trendsFilter: { hideWeekends: true } } as Partial<TrendsQuery>,
            {},
            { dateRange: { daysOfWeek: [1, 2, 3] }, trendsFilter: { hideWeekends: undefined } },
        ],
        [
            'does not add trendsFilter key when hideWeekends was not set',
            [1, 2, 3],
            { kind: 'TrendsQuery', trendsFilter: {} } as Partial<TrendsQuery>,
            {},
            { dateRange: { daysOfWeek: [1, 2, 3] } },
        ],
    ])('computeDaysOfWeekUpdate: %s', (_name, days, querySource, dateRange, expected) => {
        expect(computeDaysOfWeekUpdate(days, querySource, dateRange)).toEqual(expected)
    })
})
