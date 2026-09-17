import { deriveVerdict } from './traceSummaryLoader'

describe('deriveVerdict', () => {
    it('reads a true result as a pass for a normal evaluation', () => {
        expect(deriveVerdict('true', null, false)).toBe('pass')
        expect(deriveVerdict('false', null, false)).toBe('fail')
    })

    it('reads a true result as a fail for a detector', () => {
        expect(deriveVerdict('true', null, true)).toBe('fail')
        expect(deriveVerdict('false', null, true)).toBe('pass')
    })

    it.each([false, true])('reports a non-applicable result as n/a (detector: %s)', (trueIsFailure) => {
        expect(deriveVerdict('true', 'false', trueIsFailure)).toBe('n/a')
    })

    it.each([false, true])('reports an unreadable result as unknown (detector: %s)', (trueIsFailure) => {
        expect(deriveVerdict(null, null, trueIsFailure)).toBe('unknown')
        expect(deriveVerdict('nonsense', null, trueIsFailure)).toBe('unknown')
    })
})
