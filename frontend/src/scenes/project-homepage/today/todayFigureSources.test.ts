import { dayjs } from 'lib/dayjs'

import { anchorToday } from './todayFigureSources'

describe('todayFigureSources', () => {
    test.each([
        [
            'an older quote',
            '2026-09-04T10:00:00Z',
            'A session from today hit it.',
            'A session from today [4 Sep] hit it.',
        ],
        ['a quote from today', '2026-10-03T08:00:00Z', 'A session from today hit it.', 'A session from today hit it.'],
    ])('dates "today" in %s', (_, date, text, expected) => {
        expect(anchorToday(text, date, dayjs('2026-10-03T12:00:00Z'))).toEqual(expected)
    })
})
