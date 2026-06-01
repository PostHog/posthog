import { nearestOperator } from './operatorSuggestion'

const OPERATORS = new Set(['select', 'reject', 'coalesce', 'join', 'omit', 'stringify', 'literal'])

describe('nearestOperator', () => {
    it('suggests an operator one edit away from a typo', () => {
        expect(nearestOperator('selct', OPERATORS)).toBe('select') // deletion
        expect(nearestOperator('joins', OPERATORS)).toBe('join') // insertion
        expect(nearestOperator('omat', OPERATORS)).toBe('omit') // substitution
    })

    it('returns nothing when no operator is close', () => {
        expect(nearestOperator('completely_different', OPERATORS)).toBeUndefined()
    })

    it('does not suggest for an exact (non-typo) match', () => {
        expect(nearestOperator('select', OPERATORS)).toBeUndefined()
    })
})
