import { computeIncompleteOffset, detectIntervalFromXData, findIncompleteRange } from './incompletePeriodUtils'

// Current time for all offset tests: 2024-06-15T12:00:00Z (a Saturday)
const NOW = '2024-06-15T12:00:00Z'

const HOURLY_LABELS = [
    '2024-06-15T10:00:00Z',
    '2024-06-15T11:00:00Z',
    '2024-06-15T12:00:00Z',
    '2024-06-15T13:00:00Z',
    '2024-06-15T14:00:00Z',
]
const DAILY_LABELS = ['2024-06-12', '2024-06-13', '2024-06-14', '2024-06-15', '2024-06-16']
const DAILY_LABELS_REVERSED = [...DAILY_LABELS].reverse()
const WEEKLY_LABELS = ['2024-06-03', '2024-06-10', '2024-06-17']
const MONTHLY_LABELS = ['2024-04-01', '2024-05-01', '2024-06-01', '2024-07-01']

describe('incompletePeriodUtils', () => {
    describe('detectIntervalFromXData', () => {
        it.each([
            ['empty array', [], null],
            ['single element', ['2024-06-15'], null],
            ['invalid first date', ['invalid', '2024-06-16'], null],
            ['invalid second date', ['2024-06-15', 'not-a-date'], null],
            ['both dates invalid', ['foo', 'bar'], null],
        ])('returns null for %s', (_name, xLabels, expected) => {
            expect(detectIntervalFromXData(xLabels)).toBe(expected)
        })

        it.each([
            ['1h apart', ['2024-06-15T10:00:00Z', '2024-06-15T11:00:00Z'], 'hour'],
            ['consecutive hours', ['2024-06-15T00:00:00Z', '2024-06-15T01:00:00Z'], 'hour'],
            ['2h apart (rounds to day)', ['2024-06-15T00:00:00Z', '2024-06-15T02:00:00Z'], 'day'],
            ['24h apart', ['2024-06-15T00:00:00Z', '2024-06-16T00:00:00Z', '2024-06-17T00:00:00Z'], 'day'],
            ['consecutive days', ['2024-06-01', '2024-06-02', '2024-06-03'], 'day'],
            ['3 days apart (rounds to week)', ['2024-06-01T00:00:00Z', '2024-06-03T00:00:00Z'], 'week'],
            ['7 days apart', ['2024-06-01T00:00:00Z', '2024-06-08T00:00:00Z', '2024-06-15T00:00:00Z'], 'week'],
            ['consecutive weeks', ['2024-06-03T00:00:00Z', '2024-06-10T00:00:00Z', '2024-06-17T00:00:00Z'], 'week'],
            ['10 days apart (rounds to month)', ['2024-06-01T00:00:00Z', '2024-06-10T00:00:00Z'], 'month'],
            ['30 days apart', ['2024-01-01T00:00:00Z', '2024-01-31T00:00:00Z', '2024-03-01T00:00:00Z'], 'month'],
            ['consecutive months', ['2024-01-01T00:00:00Z', '2024-02-01T00:00:00Z', '2024-03-01T00:00:00Z'], 'month'],
            ['reverse daily', ['2024-06-03', '2024-06-02', '2024-06-01'], 'day'],
            ['reverse weekly', ['2024-06-17T00:00:00Z', '2024-06-10T00:00:00Z', '2024-06-03T00:00:00Z'], 'week'],
            ['reverse hourly', ['2024-06-15T11:00:00Z', '2024-06-15T10:00:00Z'], 'hour'],
        ])('detects interval: %s → %s', (_name, xLabels, expected) => {
            expect(detectIntervalFromXData(xLabels)).toBe(expected)
        })
    })

    describe('computeIncompleteOffset', () => {
        beforeEach(() => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date(NOW))
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it.each([
            ['empty array', [], 'day', 0],
            ['all past (daily)', ['2024-06-01', '2024-06-02', '2024-06-03'], 'day', 0],
            ['all past (hourly)', ['2024-06-14T10:00:00Z', '2024-06-14T11:00:00Z'], 'hour', 0],
            ['all past (weekly)', ['2024-06-01T00:00:00Z', '2024-06-08T00:00:00Z'], 'week', 0],
        ])('returns 0 when %s', (_name, xLabels, interval, expected) => {
            expect(computeIncompleteOffset(xLabels, interval)).toBe(expected)
        })

        it.each([
            ['daily — today is last point', DAILY_LABELS.slice(0, -1), 'day', -1],
            ['daily — today + future', DAILY_LABELS, 'day', -2],
            ['hourly — current hour onwards', HOURLY_LABELS, 'hour', -3],
            ['weekly — current week onwards', WEEKLY_LABELS, 'week', -2],
            ['monthly — current month onwards', MONTHLY_LABELS, 'month', -2],
        ])('finds incomplete: %s → offset %i', (_name, xLabels, interval, expected) => {
            expect(computeIncompleteOffset(xLabels, interval)).toBe(expected)
        })

        it.each([
            ['d → day', ['2024-06-14', '2024-06-15'], 'd', -1],
            ['h → hour', ['2024-06-15T11:00:00Z', '2024-06-15T12:00:00Z'], 'h', -1],
            ['w → week', WEEKLY_LABELS.slice(1), 'w', -2],
            ['m → month', ['2024-05-01', '2024-06-01'], 'm', -1],
        ])('normalizes shorthand %s', (_name, xLabels, interval, expected) => {
            expect(computeIncompleteOffset(xLabels, interval)).toBe(expected)
        })

        it('treats midnight boundary as incomplete', () => {
            const xLabels = ['2024-06-14T23:00:00Z', '2024-06-15T00:00:00Z', '2024-06-15T23:00:00Z']
            expect(computeIncompleteOffset(xLabels, 'day')).toBe(-2)
        })

        it('marks current day incomplete at start of day', () => {
            jest.setSystemTime(new Date('2024-06-15T00:00:00Z'))
            expect(computeIncompleteOffset(['2024-06-14', '2024-06-15'], 'day')).toBe(-1)
        })

        it('marks current day incomplete at end of day', () => {
            jest.setSystemTime(new Date('2024-06-15T23:59:59Z'))
            expect(computeIncompleteOffset(['2024-06-14', '2024-06-15'], 'day')).toBe(-1)
        })

        it('handles hourly data spanning midnight', () => {
            jest.setSystemTime(new Date('2024-06-15T00:30:00Z'))
            const xLabels = [
                '2024-06-14T22:00:00Z',
                '2024-06-14T23:00:00Z',
                '2024-06-15T00:00:00Z',
                '2024-06-15T01:00:00Z',
            ]
            expect(computeIncompleteOffset(xLabels, 'hour')).toBe(-2)
        })
    })

    describe('findIncompleteRange', () => {
        beforeEach(() => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date(NOW))
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it.each([
            ['empty array', [], 'day' as const, null],
            ['all past', ['2024-06-01', '2024-06-02', '2024-06-03'], 'day' as const, null],
        ])('returns null when %s', (_name, xLabels, interval, expected) => {
            expect(findIncompleteRange(xLabels, interval)).toBe(expected)
        })

        it.each([
            ['ascending — today at end', DAILY_LABELS, 'day' as const, { from: 3, to: 4, count: 2 }],
            ['descending — today at start', DAILY_LABELS_REVERSED, 'day' as const, { from: 0, to: 1, count: 2 }],
            ['ascending — hourly', HOURLY_LABELS, 'hour' as const, { from: 2, to: 4, count: 3 }],
            ['ascending — weekly', WEEKLY_LABELS, 'week' as const, { from: 1, to: 2, count: 2 }],
        ])('finds range: %s', (_name, xLabels, interval, expected) => {
            expect(findIncompleteRange(xLabels, interval)).toEqual(expected)
        })
    })
})
