import { DateDisplayParts, FormatDateDisplayInput, formatDateDisplay } from './formatDateDisplay'

const WEDNESDAY = '2026-01-14T14:35:27Z'
const WEDNESDAY_A_YEAR_EARLIER = '2025-01-14T14:35:27Z'
const RESOLVED_DATE_RANGE = { date_from: '2026-01-07T00:00:00Z', date_to: '2026-01-15T23:59:59Z' }

interface FormatDateDisplayCase {
    name: string
    now?: string
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
        name: 'day in a prior year keeps the short format',
        input: { date: '2025-10-29T10:00:00Z', interval: 'day', timezone: 'UTC' },
        expected: { highlight: 'We', primary: '29 Oct', secondary: null, weekEnd: null },
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
    {
        name: 'full date: day in the current year shows a three-letter weekday and no year',
        input: { date: WEDNESDAY, interval: 'day', timezone: 'UTC', showFullDate: true },
        expected: { highlight: 'Wed', primary: '14 Jan', secondary: null, weekEnd: null },
    },
    {
        name: 'full date: day in a prior year shows the year after the month',
        input: { date: '2025-10-29T10:00:00Z', interval: 'day', timezone: 'UTC', showFullDate: true },
        expected: { highlight: 'Wed', primary: '29 Oct 2025', secondary: null, weekEnd: null },
    },
    {
        name: 'full date: day in a future year shows the year',
        input: { date: '2027-01-14T10:00:00Z', interval: 'day', timezone: 'UTC', showFullDate: true },
        expected: { highlight: 'Thu', primary: '14 Jan 2027', secondary: null, weekEnd: null },
    },
    {
        name: 'full date: day that the project timezone moves into the current year',
        input: { date: '2025-12-31T20:00:00Z', interval: 'day', timezone: 'Asia/Tokyo', showFullDate: true },
        expected: { highlight: 'Thu', primary: '1 Jan', secondary: null, weekEnd: null },
    },
    {
        name: 'full date: day in the current year of the project timezone while the browser is still in the prior year',
        now: '2025-12-31T20:00:00Z',
        input: { date: '2026-01-01T00:00:00Z', interval: 'day', timezone: 'Asia/Tokyo', showFullDate: true },
        expected: { highlight: 'Thu', primary: '1 Jan', secondary: null, weekEnd: null },
    },
    {
        name: 'full date: week in a prior year shows the year',
        input: { date: '2025-12-29T00:00:00Z', interval: 'week', timezone: 'UTC', showFullDate: true },
        expected: { highlight: 'Mon', primary: '29 Dec 2025', secondary: null, weekEnd: null },
    },
    {
        name: 'full date: week range that starts in a prior year',
        input: {
            date: '2025-12-29T00:00:00Z',
            interval: 'week',
            resolvedDateRange: { date_from: '2025-12-01T00:00:00Z', date_to: '2026-01-15T23:59:59Z' },
            timezone: 'UTC',
            weekStartDay: 1,
            showFullDate: true,
        },
        expected: { highlight: 'Mon', primary: '29 Dec 2025', secondary: null, weekEnd: '2026-01-04T23:59:59.999Z' },
    },
    {
        name: 'full date: week range end in the current year shows no year',
        input: { date: '2026-01-04T23:59:59.999Z', interval: 'day', timezone: 'UTC', showFullDate: true },
        expected: { highlight: 'Sun', primary: '4 Jan', secondary: null, weekEnd: null },
    },
    {
        name: 'full date: hour in a prior year puts a comma before the year',
        input: { date: '2025-12-29T14:35:27Z', interval: 'hour', timezone: 'UTC', showFullDate: true },
        expected: { highlight: 'Dec 29, 2025', primary: '14:00', secondary: null, weekEnd: null },
    },
    {
        name: 'full date: minute in a prior year puts a comma before the year',
        input: { date: '2025-12-29T14:35:27Z', interval: 'minute', timezone: 'UTC', showFullDate: true },
        expected: { highlight: 'Dec 29, 2025', primary: '14:35:00', secondary: null, weekEnd: null },
    },
    {
        name: 'full date: second in a prior year puts a comma before the year',
        input: { date: '2025-12-29T14:35:27Z', interval: 'second', timezone: 'UTC', showFullDate: true },
        expected: { highlight: 'Dec 29, 2025', primary: '14:35:27', secondary: null, weekEnd: null },
    },
    {
        name: 'full date: month in a prior year keeps its format',
        input: { date: '2025-03-10T00:00:00Z', interval: 'month', timezone: 'UTC', showFullDate: true },
        expected: { highlight: '2025', primary: 'Mar', secondary: null, weekEnd: null },
    },
    {
        name: 'full date: quarter in a prior year keeps its format',
        input: { date: '2025-03-10T00:00:00Z', interval: 'quarter', timezone: 'UTC', showFullDate: true },
        expected: { highlight: '2025', primary: 'Q1', secondary: null, weekEnd: null },
    },
]

describe('formatDateDisplay', () => {
    afterEach(() => {
        jest.useRealTimers()
    })

    test.each(cases)('$name', ({ now, input, expected }) => {
        jest.useFakeTimers().setSystemTime(new Date(now ?? '2026-01-15T12:00:00Z'))
        expect(formatDateDisplay(input)).toEqual(expected)
    })
})
