import { daysOfWeekLabel, getEffectiveDaysOfWeek } from './daysOfWeekFilterUtils'

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
})
