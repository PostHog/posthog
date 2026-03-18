import { getNextRetryMs } from '../../src/utils/retries'

jest.useFakeTimers()
jest.spyOn(global, 'setTimeout')

describe('getNextRetryMs', () => {
    it('returns the correct number of milliseconds with a multiplier of 1', () => {
        expect(getNextRetryMs(500, 1, 1)).toBe(500)
        expect(getNextRetryMs(500, 1, 2)).toBe(500)
        expect(getNextRetryMs(500, 1, 3)).toBe(500)
        expect(getNextRetryMs(500, 1, 4)).toBe(500)
        expect(getNextRetryMs(500, 1, 5)).toBe(500)
    })

    it('returns the correct number of milliseconds with a multiplier of 2', () => {
        expect(getNextRetryMs(4000, 2, 1)).toBe(4000)
        expect(getNextRetryMs(4000, 2, 2)).toBe(8000)
        expect(getNextRetryMs(4000, 2, 3)).toBe(16000)
        expect(getNextRetryMs(4000, 2, 4)).toBe(32000)
        expect(getNextRetryMs(4000, 2, 5)).toBe(64000)
    })

    it('throws on attempt below 0', () => {
        expect(() => getNextRetryMs(4000, 2, 0)).toThrow('Attempts are indexed starting with 1')
        expect(() => getNextRetryMs(4000, 2, -1)).toThrow('Attempts are indexed starting with 1')
    })
})
