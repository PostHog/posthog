import { formatSilence } from './turnGaps'

describe('turnGaps', () => {
    test.each([
        [60_000, '1 minute later'],
        [120_000, '2 minutes later'],
        [3_570_000, '1 hour later'],
        [3_600_000, '1 hour later'],
        [10_800_000, '3 hours later'],
        [85_320_000, '1 day later'],
        [259_200_000, '3 days later'],
    ])('formatSilence(%s) is %s', (ms, text) => {
        expect(formatSilence(ms)).toBe(text)
    })
})
