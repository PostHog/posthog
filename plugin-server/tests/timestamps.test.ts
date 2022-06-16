import { parseDate } from '../src/worker/ingestion/timestamps'

describe('utils', () => {
    describe('parseDate', () => {
        const timestamps = [
            '2021-10-29',
            '2021-10-29 00:00:00',
            '2021-10-29 00:00:00.000000',
            '2021-10-29T00:00:00.000Z',
            '2021-10-29 00:00:00+00:00',
            '2021-10-29T00:00:00.000-00:00',
            '2021-10-29T00:00:00.000',
            '2021-10-29T00:00:00.000+00:00',
            '2021-W43-5',
            '2021-302',
        ]

        test.each(timestamps)('parses %s', (timestamp) => {
            const parsedTimestamp = parseDate(timestamp)
            expect(parsedTimestamp.year).toBe(2021)
            expect(parsedTimestamp.month).toBe(10)
            expect(parsedTimestamp.day).toBe(29)
            expect(parsedTimestamp.hour).toBe(0)
            expect(parsedTimestamp.minute).toBe(0)
            expect(parsedTimestamp.second).toBe(0)
            expect(parsedTimestamp.millisecond).toBe(0)
        })
    })
})
