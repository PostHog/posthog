import { sessionTimestampHint } from './sessionLookup'

describe('sessionLookup', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-09-01T12:00:00Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    test.each<[string, string, string | null]>([
        ['a past time', 'timestamp=2026-08-01T10:00:00Z', '2026-08-01T10:00:00.000Z'],
        [
            'a time whose plus sign arrived as a space',
            'timestamp=2026-08-01T10:00:00 02:00',
            '2026-08-01T08:00:00.000Z',
        ],
        [
            'a time just inside the day a fast clock may run ahead',
            'timestamp=2026-09-02T11:59:59Z',
            '2026-09-02T11:59:59.000Z',
        ],
        ['a time more than a day ahead', 'timestamp=2026-09-02T12:00:01Z', null],
        ['the start of 1970', 'timestamp=1970-01-01T00:00:00Z', '1970-01-01T00:00:00.000Z'],
        ['a time before 1970', 'timestamp=1969-12-31T23:59:59Z', null],
        ['text that is no time', 'timestamp=not-a-date', null],
        ['no time', 'session=session-1', null],
    ])('reads %s from a link', (_name, search, hint) => {
        expect(sessionTimestampHint(`?${search}`)).toEqual(hint)
    })
})
