import { isEvaluableCondition } from './hogflow-utils'

describe('isEvaluableCondition', () => {
    it('treats an always-true condition as absent (versioned and legacy compiler forms)', () => {
        // Empty filters compile to the TRUE op as the whole program. Both forms must be caught.
        expect(isEvaluableCondition({ filters: { bytecode: ['_H', 1, 29] } })).toBe(false)
        expect(isEvaluableCondition({ filters: { bytecode: ['_h', 29] } })).toBe(false)
    })

    it('treats a missing, empty, or non-array bytecode as absent', () => {
        expect(isEvaluableCondition(undefined)).toBe(false)
        expect(isEvaluableCondition({})).toBe(false)
        expect(isEvaluableCondition({ filters: {} })).toBe(false)
        expect(isEvaluableCondition({ filters: { bytecode: [] } })).toBe(false)
        expect(isEvaluableCondition({ filters: { bytecode: undefined } })).toBe(false)
    })

    it('evaluates a real condition regardless of how the filter is expressed', () => {
        // A property condition carries a real comparison program.
        expect(isEvaluableCondition({ filters: { bytecode: ['_H', 1, 32, 'x', 1, 1, 11] } })).toBe(true)
        // The guard must NOT key on a top-level `properties` array: a real condition expressed
        // through events/actions filters has no `properties` but still has real bytecode.
        expect(isEvaluableCondition({ filters: { bytecode: ['_H', 1, 32, '$pageview', 32, 'event', 1, 1, 11] } })).toBe(
            true
        )
    })
})
