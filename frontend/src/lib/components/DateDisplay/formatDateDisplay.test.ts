import { DateDisplayParts, FormatDateDisplayInput, formatDateDisplay } from './formatDateDisplay'

const WEDNESDAY = '2026-01-14T14:35:27Z'
const WEDNESDAY_A_YEAR_EARLIER = '2025-01-14T14:35:27Z'
const RESOLVED_DATE_RANGE = { date_from: '2026-01-07T00:00:00Z', date_to: '2026-01-15T23:59:59Z' }

interface FormatDateDisplayCase {
    name: string
    input: FormatDateDisplayInput
    expected: DateDisplayParts
}

const cases: FormatDateDisplayCase[] = [
    {
        name: 'second',
        input: { date: WEDNESDAY, interval: 'second', timezone: 'UTC' },
        expected: { highlight: 'Jan 14', primary: '14:35:27', secondary: null, weekEnd: null },
    },
    {
        name: 'second with a secondary date',
        input: { date: WEDNESDAY, secondaryDate: WEDNESDAY_A_YEAR_EARLIER, interval: 'second', timezone: 'UTC' },
        expected: { highlight: 'Jan 14', primary: '14:35:27', secondary: '14:35:27', weekEnd: null },
    },
    {
        name: 'minute',
        input: { date: WEDNESDAY, interval: 'minute', timezone: 'UTC' },
        expected: { highlight: 'Jan 14', primary: '14:35:00', secondary: null, weekEnd: null },
    },
    {
        name: 'minute with a secondary date',
        input: { date: WEDNESDAY, secondaryDate: WEDNESDAY_A_YEAR_EARLIER, interval: 'minute', timezone: 'UTC' },
        expected: { highlight: 'Jan 14', primary: '14:35:00', secondary: '14:35:00', weekEnd: null },
    },
    {
        name: 'hour',
        input: { date: WEDNESDAY, interval: 'hour', timezone: 'UTC' },
        expected: { highlight: 'Jan 14', primary: '14:00', secondary: null, weekEnd: null },
    },
    {
        name: 'hour with a secondary date',
        input: { date: WEDNESDAY, secondaryDate: WEDNESDAY_A_YEAR_EARLIER, interval: 'hour', timezone: 'UTC' },
        expected: { highlight: 'Jan 14', primary: '14:00', secondary: '14:00', weekEnd: null },
    },
    {
        name: 'day',
        input: { date: WEDNESDAY, interval: 'day', timezone: 'UTC' },
        expected: { highlight: 'We', primary: '14 Jan', secondary: null, weekEnd: null },
    },
    {
        name: 'day with a secondary date',
        input: { date: WEDNESDAY, secondaryDate: WEDNESDAY_A_YEAR_EARLIER, interval: 'day', timezone: 'UTC' },
        expected: { highlight: 'We', primary: '14 Jan', secondary: '14 Jan', weekEnd: null },
    },
    {
        name: 'week',
        input: { date: WEDNESDAY, interval: 'week', timezone: 'UTC' },
        expected: { highlight: 'We', primary: '14 Jan', secondary: null, weekEnd: null },
    },
    {
        name: 'week with a secondary date',
        input: { date: WEDNESDAY, secondaryDate: WEDNESDAY_A_YEAR_EARLIER, interval: 'week', timezone: 'UTC' },
        expected: { highlight: 'We', primary: '14 Jan', secondary: '14 Jan', weekEnd: null },
    },
    {
        name: 'week range starting at the resolved date range start',
        input: {
            date: '2026-01-04T00:00:00Z',
            interval: 'week',
            resolvedDateRange: RESOLVED_DATE_RANGE,
            timezone: 'UTC',
            weekStartDay: 0,
        },
        expected: { highlight: 'We', primary: '7 Jan', secondary: null, weekEnd: '2026-01-10T23:59:59.999Z' },
    },
    {
        name: 'week range ending at the resolved date range end',
        input: {
            date: '2026-01-11T00:00:00Z',
            interval: 'week',
            resolvedDateRange: RESOLVED_DATE_RANGE,
            timezone: 'UTC',
            weekStartDay: 0,
        },
        expected: { highlight: 'Su', primary: '11 Jan', secondary: null, weekEnd: '2026-01-15T23:59:59.000Z' },
    },
    {
        name: 'month',
        input: { date: WEDNESDAY, interval: 'month', timezone: 'UTC' },
        expected: { highlight: '2026', primary: 'Jan', secondary: null, weekEnd: null },
    },
    {
        name: 'month with a secondary date',
        input: { date: WEDNESDAY, secondaryDate: WEDNESDAY_A_YEAR_EARLIER, interval: 'month', timezone: 'UTC' },
        expected: { highlight: '2026', primary: 'Jan', secondary: 'Jan', weekEnd: null },
    },
    {
        name: 'quarter',
        input: { date: WEDNESDAY, interval: 'quarter', timezone: 'UTC' },
        expected: { highlight: '2026', primary: 'Q1', secondary: null, weekEnd: null },
    },
    {
        name: 'quarter with a secondary date',
        input: { date: WEDNESDAY, secondaryDate: WEDNESDAY_A_YEAR_EARLIER, interval: 'quarter', timezone: 'UTC' },
        expected: { highlight: '2026', primary: 'Q1', secondary: 'Q1', weekEnd: null },
    },
    {
        name: 'year',
        input: { date: WEDNESDAY, interval: 'year', timezone: 'UTC' },
        expected: { highlight: '', primary: '2026', secondary: null, weekEnd: null },
    },
    {
        name: 'year with a secondary date',
        input: { date: WEDNESDAY, secondaryDate: WEDNESDAY_A_YEAR_EARLIER, interval: 'year', timezone: 'UTC' },
        expected: { highlight: '', primary: '2026', secondary: '2025', weekEnd: null },
    },
]

describe('formatDateDisplay', () => {
    beforeEach(() => {
        jest.useFakeTimers().setSystemTime(new Date('2026-01-15T12:00:00Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    test.each(cases)('$name', ({ input, expected }) => {
        expect(formatDateDisplay(input)).toEqual(expected)
    })
})
