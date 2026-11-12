import { getMatrixHogQLScope, getMatrixHogQLScopeWarning } from './dotMatrixHogQLScope'
import { createMatrixHogQLQuery } from './dotMatrixTileQuery'

describe('dot matrix query scope', () => {
    it.each([
        "SELECT '{filters}' AS row, 1 AS column",
        'SELECT 1 -- {filters}\n',
        'SELECT 1 /* {account_id} */',
        'SELECT "{filters}" FROM events',
        "SELECT 'it''s {filters}', 1",
    ])('ignores placeholders in quoted text and comments (%s)', (query) => {
        expect(getMatrixHogQLScopeWarning(query)).toContain('other accounts')
        expect(() => createMatrixHogQLQuery(query, { accountId: 'a', weeks: 8 })).not.toThrow()
    })

    it.each(['SELECT 1 FROM events WHERE { filters }', 'SELECT 1 FROM events e WHERE {filters(events as e)}'])(
        'requires account context for active group filters (%s)',
        (query) => {
            expect(getMatrixHogQLScope(query).usesFilters).toBe(true)
            expect(getMatrixHogQLScopeWarning(query)).toBeNull()
            expect(() => createMatrixHogQLQuery(query, { accountId: 'a', weeks: 8 })).toThrow('Link this account')
        }
    )

    it('distinguishes date placeholders from account filters and recognizes explicit account values', () => {
        expect(getMatrixHogQLScope("SELECT {filters.interval('week')} FROM events").usesFilters).toBe(false)
        expect(getMatrixHogQLScopeWarning('SELECT * FROM warehouse WHERE org_id = {account_external_id}')).toBeNull()
        expect(getMatrixHogQLScope('SELECT * FROM warehouse WHERE account_id IN {account_ids}').usesAccountIds).toBe(
            true
        )
    })
})
