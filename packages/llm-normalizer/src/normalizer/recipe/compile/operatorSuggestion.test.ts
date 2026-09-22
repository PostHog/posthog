import { nearestOperator } from './operatorSuggestion'

const OPERATORS = new Set(['select', 'reject', 'coalesce', 'join', 'omit', 'stringify', 'literal'])

describe('nearestOperator', () => {
    it.each([
        ['selct', 'select', 'deletion'],
        ['joins', 'join', 'insertion'],
        ['omat', 'omit', 'substitution'],
    ])('suggests %s → %s (%s)', (typo, expected) => {
        expect(nearestOperator(typo, OPERATORS)).toBe(expected)
    })

    it('returns nothing when no operator is close', () => {
        expect(nearestOperator('completely_different', OPERATORS)).toBeUndefined()
    })

    it('does not suggest for an exact (non-typo) match', () => {
        expect(nearestOperator('select', OPERATORS)).toBeUndefined()
    })
})
