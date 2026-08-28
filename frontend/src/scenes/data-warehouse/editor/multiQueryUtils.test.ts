import { findInnermostSelectAtOffset } from './multiQueryUtils'

describe('multiQueryUtils', () => {
    describe('findInnermostSelectAtOffset', () => {
        it('returns null for a flat query with no subqueries', async () => {
            const query = 'SELECT * FROM events'
            const result = await findInnermostSelectAtOffset(query, 5, 0)
            expect(result).toBeNull()
        })

        it('finds the inner SELECT in a FROM subquery', async () => {
            const query = 'SELECT * FROM (SELECT id FROM events)'
            // Place cursor inside the inner SELECT (offset ~20, inside "SELECT id")
            const result = await findInnermostSelectAtOffset(query, 20, 0)
            expect(result).not.toBeNull()
            expect(result!.query).toContain('SELECT id FROM events')
        })

        it('returns null when cursor is in the outer query but not inside a subquery', async () => {
            const query = 'SELECT * FROM (SELECT id FROM events)'
            // Place cursor at the very start — inside "SELECT *" of the outer query
            const result = await findInnermostSelectAtOffset(query, 3, 0)
            expect(result).toBeNull()
        })

        it('handles queryStartOffset correctly', async () => {
            const query = 'SELECT * FROM (SELECT id FROM events)'
            const offset = 100
            // Cursor inside the inner SELECT, with a start offset
            const result = await findInnermostSelectAtOffset(query, offset + 20, offset)
            expect(result).not.toBeNull()
            expect(result!.start).toBeGreaterThanOrEqual(offset)
            expect(result!.end).toBeLessThanOrEqual(offset + query.length)
        })

        it('finds the innermost of doubly-nested subqueries', async () => {
            const query = 'SELECT * FROM (SELECT * FROM (SELECT 1))'
            // Cursor inside the innermost SELECT (offset ~35, inside "SELECT 1")
            const result = await findInnermostSelectAtOffset(query, 35, 0)
            expect(result).not.toBeNull()
            expect(result!.query).toContain('SELECT 1')
        })

        it('returns null for invalid SQL', async () => {
            const result = await findInnermostSelectAtOffset('NOT VALID SQL', 5, 0)
            expect(result).toBeNull()
        })

        it('finds subquery in a CTE', async () => {
            const query = 'WITH x AS (SELECT 1) SELECT * FROM x'
            // Cursor inside "SELECT 1" (offset ~15)
            const result = await findInnermostSelectAtOffset(query, 15, 0)
            expect(result).not.toBeNull()
            expect(result!.query).toContain('SELECT 1')
        })
    })
})
