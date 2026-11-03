import { deriveVerdict } from './traceSummaryLoader'

describe('deriveVerdict', () => {
    it.each([
        ['true', 'false'],
        ['TRUE', 'FALSE'],
        [true, false],
    ])('reads %s as a pass and %s as a fail for a normal evaluation', (passing, failing) => {
        expect(deriveVerdict(passing, null, false)).toBe('pass')
        expect(deriveVerdict(failing, null, false)).toBe('fail')
    })

    it.each([
        ['true', 'false'],
        [true, false],
    ])('reads %s as a fail and %s as a pass for a detector', (failing, passing) => {
        expect(deriveVerdict(failing, null, true)).toBe('fail')
        expect(deriveVerdict(passing, null, true)).toBe('pass')
    })

    it.each([
        ['true', 'false', false],
        ['true', 'false', true],
        [true, false, false],
        [true, false, true],
    ])('reports %s as n/a when applicable is %s (detector: %s)', (result, applicable, trueIsFailure) => {
        expect(deriveVerdict(result, applicable, trueIsFailure)).toBe('n/a')
    })

    it('keeps a boolean true applicable from hiding the verdict', () => {
        expect(deriveVerdict(true, true, false)).toBe('pass')
    })

    it.each([false, true])('reports an unreadable result as unknown (detector: %s)', (trueIsFailure) => {
        expect(deriveVerdict(null, null, trueIsFailure)).toBe('unknown')
        expect(deriveVerdict('nonsense', null, trueIsFailure)).toBe('unknown')
    })
})
