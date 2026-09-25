import { fireEvent, render, screen } from '@testing-library/react'

import { resolveSaveCandidates, SaveTargetCycler } from './SaveTargetCycler'

describe('SaveTargetCycler', () => {
    describe('resolveSaveCandidates', () => {
        it('keeps the full query as a candidate behind a selection', () => {
            const result = resolveSaveCandidates('SELECT 1 FROM events', 5, 'SELECT 1')
            expect(result).toEqual({
                queries: ['SELECT 1', 'SELECT 1 FROM events'],
                initialIndex: 0,
                labels: ['Selection', 'Full query'],
            })
        })

        it('keeps every statement as a candidate behind a selection', () => {
            const result = resolveSaveCandidates('SELECT 1; SELECT 2', 5, 'SELECT 1')
            expect(result).toEqual({
                queries: ['SELECT 1', 'SELECT 1', 'SELECT 2'],
                initialIndex: 0,
                labels: ['Selection', 'Query 1 of 2', 'Query 2 of 2'],
            })
        })

        it('does not default to a selection that cannot start a statement', () => {
            const result = resolveSaveCandidates('WITH sample AS (SELECT 1) SELECT * FROM sample', 6, 'sa')
            expect(result.queries).toEqual(['sa', 'WITH sample AS (SELECT 1) SELECT * FROM sample'])
            expect(result.initialIndex).toBe(1)
        })

        it('ignores whitespace-only selections and falls through to cursor logic', () => {
            const result = resolveSaveCandidates('SELECT 1; SELECT 2', 12, '   \n  ')
            expect(result.queries).toEqual(['SELECT 1', 'SELECT 2'])
            // cursor at offset 12 is inside the second query
            expect(result.initialIndex).toBe(1)
        })

        it('returns a single-query candidate when the editor has one statement', () => {
            const result = resolveSaveCandidates('SELECT 1', 0, null)
            expect(result).toEqual({
                queries: ['SELECT 1'],
                initialIndex: 0,
                labels: ['Full query'],
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
            expect(result.queries).toEqual([''])
        })
    })

    it('offers a way back to the full query when a selection is active', () => {
        const candidates = resolveSaveCandidates('SELECT 1 FROM events', 5, 'SELECT 1')
        const onChange = jest.fn()
        render(<SaveTargetCycler candidates={candidates} onChange={onChange} />)

        expect(screen.getByText('Saving: Selection')).toBeTruthy()

        fireEvent.click(screen.getByLabelText('Next save target'))

        expect(screen.getByText('Saving: Full query')).toBeTruthy()
        expect(onChange).toHaveBeenLastCalledWith('SELECT 1 FROM events', 1)
    })
})
