import { filterDateToISOString, toFilterDates } from './advancedActivityLogsLogic'

const PROJECT_TIMEZONE = 'America/New_York'

describe('activity log dates', () => {
    test.each([
        ['time without offset reads in project timezone', '2026-11-14T04:10:00', '2026-11-14T09:10:00.000Z'],
        ['whole day reads in project timezone', '2026-11-14', '2026-11-14T05:00:00.000Z'],
        ['UTC instant keeps its instant', '2026-11-14T09:10:00Z', '2026-11-14T09:10:00.000Z'],
        ['numeric offset keeps its instant', '2026-11-14T11:10:00+02:00', '2026-11-14T09:10:00.000Z'],
    ])('filterDateToISOString: %s', (_name, value, expected) => {
        expect(filterDateToISOString(value, PROJECT_TIMEZONE)).toEqual(expected)
    })

    test('filterDateToISOString: invalid value returns undefined', () => {
        expect(filterDateToISOString('not-a-date', PROJECT_TIMEZONE)).toBeUndefined()
    })

    test.each([
        [
            'jump result is stored in project time',
            '2026-11-14T09:10:00Z',
            '2026-11-14T10:10:00Z',
            { start_date: '2026-11-14T04:10:00', end_date: '2026-11-14T05:10:00', hadUtcOffset: true },
        ],
        [
            'picked times are kept',
            '2026-11-14T04:10:00',
            '2026-11-14T05:10:00',
            { start_date: '2026-11-14T04:10:00', end_date: '2026-11-14T05:10:00', hadUtcOffset: false },
        ],
        ['relative range is kept', '-1h', null, { start_date: '-1h', end_date: undefined, hadUtcOffset: false }],
    ])('toFilterDates: %s', (_name, dateFrom, dateTo, expected) => {
        expect(toFilterDates(dateFrom, dateTo, PROJECT_TIMEZONE)).toEqual(expected)
    })
})
