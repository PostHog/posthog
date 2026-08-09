import { areConsecutiveDailyDates } from './sqlChartAnnotationDates'

describe('areConsecutiveDailyDates', () => {
    it.each<[string, string[], boolean]>([
        ['ascending daily dates', ['2025-01-01', '2025-01-02', '2025-01-03'], true],
        ['daily datetimes at midnight', ['2025-01-01T00:00:00', '2025-01-02T00:00:00'], true],
        ['daily datetimes across a DST switch', ['2025-03-09T00:00:00-08:00', '2025-03-10T00:00:00-07:00'], true],
        ['space-separated midnight datetimes', ['2025-01-01 00:00:00', '2025-01-02 00:00:00'], true],
        ['month boundary', ['2025-01-31', '2025-02-01'], true],
        ['year boundary', ['2024-12-31', '2025-01-01'], true],
        ['single point', ['2025-01-01'], false],
        ['no points', [], false],
        ['monthly buckets', ['2025-01-01', '2025-02-01', '2025-03-01'], false],
        ['weekly buckets', ['2025-01-06', '2025-01-13'], false],
        ['hourly buckets', ['2025-01-01T00:00:00', '2025-01-01T01:00:00'], false],
        ['gap in the middle', ['2025-01-01', '2025-01-02', '2025-01-04'], false],
        ['descending dates', ['2025-01-03', '2025-01-02', '2025-01-01'], false],
        ['duplicate dates', ['2025-01-01', '2025-01-01', '2025-01-02'], false],
        ['non-midnight timestamps', ['2025-01-01T12:00:00', '2025-01-02T12:00:00'], false],
        ['non-date strings', ['foo', 'bar'], false],
    ])('%s', (_name, dates, expected) => {
        expect(areConsecutiveDailyDates(dates)).toBe(expected)
    })
})
