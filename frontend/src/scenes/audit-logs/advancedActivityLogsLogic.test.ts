import { filterDateToISOString } from './advancedActivityLogsLogic'

describe('filterDateToISOString', () => {
    test.each([
        ['offset-free time reads as browser local', '2026-11-14T04:10:00', '2026-11-14T09:10:00.000Z'],
        ['UTC instant keeps its instant', '2026-11-14T09:10:00Z', '2026-11-14T09:10:00.000Z'],
        ['numeric offset keeps its instant', '2026-11-14T11:10:00+02:00', '2026-11-14T09:10:00.000Z'],
        ['whole day stays UTC', '2026-11-14', '2026-11-14T00:00:00.000Z'],
    ])('%s', (_name, value, expected) => {
        expect(filterDateToISOString(value, 'America/New_York')).toEqual(expected)
    })

    test('invalid value returns undefined', () => {
        expect(filterDateToISOString('not-a-date', 'America/New_York')).toBeUndefined()
    })
})
