import { getLagMultipler, maxDefined, minDefined } from '../../../../src/main/ingestion-queues/session-recording/utils'

describe('session-recording utils', () => {
    it('minDefined', () => {
        expect(minDefined(1, 2, 3)).toEqual(1)
        expect(minDefined(1, undefined, 3)).toEqual(1)
        expect(minDefined(undefined, undefined, undefined)).toEqual(undefined)
        expect(maxDefined()).toEqual(undefined)
    })

    it('maxDefined', () => {
        expect(maxDefined(1, 2, 3)).toEqual(3)
        expect(maxDefined(1, undefined, 3)).toEqual(3)
        expect(maxDefined(undefined, undefined, undefined)).toEqual(undefined)
        expect(maxDefined()).toEqual(undefined)
    })
})

describe('getLagMultipler', () => {
    const threshold = 1000
    it('returns 1 when lag is 0', () => {
        expect(getLagMultipler(0, threshold)).toEqual(1)
    })

    it('returns 1 when lag is under threshold', () => {
        expect(getLagMultipler(threshold - 1, threshold)).toEqual(1)
    })

    it('returns 0.9 when lag is double threshold', () => {
        expect(getLagMultipler(threshold * 2, threshold)).toEqual(0.9)
    })

    it('returns 0.6 when lag is 5 times the threshold', () => {
        expect(getLagMultipler(threshold * 5, threshold)).toEqual(0.6)
    })

    it('returns 0.9 when lag is 9 times the threshold', () => {
        expect(getLagMultipler(threshold * 9, threshold)).toBeGreaterThanOrEqual(0.19)
        expect(getLagMultipler(threshold * 9, threshold)).toBeLessThanOrEqual(0.2)
    })

    it('returns 0.1 when lag is 100 times the threshold', () => {
        expect(getLagMultipler(threshold * 100, threshold)).toEqual(0.1)
    })
})
