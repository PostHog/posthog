import { resolveSaveCandidates } from './SaveTargetCycler'

describe('resolveSaveCandidates', () => {
    it('returns the Selection candidate when a non-empty selection is provided', () => {
        const result = resolveSaveCandidates('SELECT 1; SELECT 2', 5, 'SELECT 1')
        expect(result).toEqual({
            queries: ['SELECT 1'],
            initialIndex: 0,
            selectionLabel: 'Selection',
        })
    })

    it('ignores whitespace-only selections and falls through to cursor logic', () => {
        const result = resolveSaveCandidates('SELECT 1; SELECT 2', 12, '   \n  ')
        expect(result.selectionLabel).toBeNull()
        expect(result.queries).toEqual(['SELECT 1', 'SELECT 2'])
        // cursor at offset 12 is inside the second query
        expect(result.initialIndex).toBe(1)
    })

    it('returns a single-query candidate when the editor has one statement', () => {
        const result = resolveSaveCandidates('SELECT 1', 0, null)
        expect(result).toEqual({
            queries: ['SELECT 1'],
            initialIndex: 0,
            selectionLabel: null,
        })
    })

    it('uses the cursor position to pick the initial index across multiple queries', () => {
        const input = 'SELECT 1; SELECT 2; SELECT 3'
        // cursor offset 22 lands inside "SELECT 3"
        const result = resolveSaveCandidates(input, 22, null)
        expect(result.queries).toEqual(['SELECT 1', 'SELECT 2', 'SELECT 3'])
        expect(result.initialIndex).toBe(2)
    })

    it('returns the nearest preceding query when the cursor is between statements', () => {
        const input = 'SELECT 1; SELECT 2'
        // cursor offset 9 is on the whitespace between the two queries
        const result = resolveSaveCandidates(input, 9, null)
        expect(result.initialIndex).toBe(0)
    })

    it('falls back to the last query when no cursor is provided', () => {
        const input = 'SELECT 1; SELECT 2; SELECT 3'
        const result = resolveSaveCandidates(input, null, null)
        expect(result.initialIndex).toBe(2)
    })

    it('falls back to the raw input when splitQueries returns nothing', () => {
        const result = resolveSaveCandidates('', null, null)
        expect(result).toEqual({
            queries: [''],
            initialIndex: 0,
            selectionLabel: null,
        })
    })
})
