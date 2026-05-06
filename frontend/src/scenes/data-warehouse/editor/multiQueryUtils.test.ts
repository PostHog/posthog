import { findInnermostSelectAtOffset, findQueryAtCursor, type QueryRange, splitQueries } from './multiQueryUtils'

describe('multiQueryUtils', () => {
    describe('splitQueries', () => {
        it('returns empty array for empty input', () => {
            expect(splitQueries('')).toEqual([])
            expect(splitQueries('   ')).toEqual([])
        })

        it('returns a single query unchanged', () => {
            const result = splitQueries('SELECT 1')
            expect(result).toHaveLength(1)
            expect(result[0].query).toBe('SELECT 1')
        })

        it('splits two semicolon-separated queries', () => {
            const result = splitQueries('SELECT 1; SELECT 2')
            expect(result).toHaveLength(2)
            expect(result[0].query).toBe('SELECT 1')
            expect(result[1].query).toBe('SELECT 2')
        })

        it('splits three queries', () => {
            const result = splitQueries('SELECT 1; SELECT 2; SELECT 3')
            expect(result).toHaveLength(3)
            expect(result[0].query).toBe('SELECT 1')
            expect(result[1].query).toBe('SELECT 2')
            expect(result[2].query).toBe('SELECT 3')
        })

        it('handles trailing semicolon', () => {
            const result = splitQueries('SELECT 1;')
            expect(result).toHaveLength(1)
            expect(result[0].query).toBe('SELECT 1')
        })

        it('handles multiline queries', () => {
            const input = `SELECT *
FROM events
WHERE timestamp > now();
SELECT count()
FROM persons`
            const result = splitQueries(input)
            expect(result).toHaveLength(2)
            expect(result[0].query).toContain('SELECT *')
            expect(result[0].query).toContain('FROM events')
            expect(result[1].query).toContain('SELECT count()')
        })

        it('returns offsets that map back to the original input', () => {
            const input = 'SELECT 1; SELECT 2'
            const result = splitQueries(input)
            for (const r of result) {
                expect(input.slice(r.start, r.end).trim()).toBe(r.query)
            }
        })

        it('does not split on semicolons inside single-quoted strings', () => {
            const result = splitQueries("SELECT 'a;b' FROM events; SELECT 2")
            expect(result).toHaveLength(2)
            expect(result[0].query).toBe("SELECT 'a;b' FROM events")
            expect(result[1].query).toBe('SELECT 2')
        })

        it('does not split on semicolons inside double-quoted strings', () => {
            const result = splitQueries('SELECT "a;b" FROM events; SELECT 2')
            expect(result).toHaveLength(2)
            expect(result[0].query).toBe('SELECT "a;b" FROM events')
        })

        it('does not split on semicolons inside backtick-quoted identifiers', () => {
            const result = splitQueries('SELECT `col;name` FROM events; SELECT 2')
            expect(result).toHaveLength(2)
            expect(result[0].query).toBe('SELECT `col;name` FROM events')
        })

        it('handles escaped quotes inside strings', () => {
            const result = splitQueries("SELECT 'it\\'s;here' FROM events; SELECT 2")
            expect(result).toHaveLength(2)
            expect(result[0].query).toContain("it\\'s;here")
        })

        it('ignores semicolons inside single-line comments', () => {
            const input = `SELECT 1 -- this; is a comment
; SELECT 2`
            const result = splitQueries(input)
            expect(result).toHaveLength(2)
            expect(result[0].query).toContain('SELECT 1')
            expect(result[1].query).toBe('SELECT 2')
        })

        it('ignores semicolons inside block comments', () => {
            const result = splitQueries('SELECT 1 /* ; not a split */ ; SELECT 2')
            expect(result).toHaveLength(2)
            expect(result[0].query).toBe('SELECT 1 /* ; not a split */')
            expect(result[1].query).toBe('SELECT 2')
        })

        it('handles multiple empty segments between semicolons', () => {
            const result = splitQueries('SELECT 1;;;SELECT 2')
            expect(result).toHaveLength(2)
            expect(result[0].query).toBe('SELECT 1')
            expect(result[1].query).toBe('SELECT 2')
        })

        it('does not split on semicolons inside parenthesized subqueries', () => {
            const input = `with evs as (
    select * from events;
) select * from evs`
            const result = splitQueries(input)
            expect(result).toHaveLength(1)
            expect(result[0].query).toBe(input)
        })

        it('handles semicolons inside nested parentheses', () => {
            const input = 'SELECT (SELECT count(*) FROM (SELECT 1; SELECT 2)); SELECT 3'
            const result = splitQueries(input)
            expect(result).toHaveLength(2)
            expect(result[0].query).toBe('SELECT (SELECT count(*) FROM (SELECT 1; SELECT 2))')
            expect(result[1].query).toBe('SELECT 3')
        })

        it('does not let an unterminated single quote mask later semicolons', () => {
            const input = "SELECT 'oops\nSELECT 2;\nSELECT 3"
            const result = splitQueries(input)
            expect(result).toHaveLength(2)
            expect(result[1].query).toBe('SELECT 3')
        })

        it('does not let an unterminated block comment mask later semicolons', () => {
            const input = 'SELECT 1 /* oops\nSELECT 2;\nSELECT 3'
            const result = splitQueries(input)
            expect(result).toHaveLength(2)
            expect(result[1].query).toBe('SELECT 3')
        })

        it('handles SQL-style doubled quotes inside a string literal', () => {
            const input = "SELECT 'it''s;ok'; SELECT 2"
            const result = splitQueries(input)
            expect(result).toHaveLength(2)
            expect(result[0].query).toBe("SELECT 'it''s;ok'")
            expect(result[1].query).toBe('SELECT 2')
        })
    })

    describe('findQueryAtCursor', () => {
        const queries: QueryRange[] = [
            { query: 'SELECT 1', start: 0, end: 8 },
            { query: 'SELECT 2', start: 10, end: 18 },
            { query: 'SELECT 3', start: 20, end: 28 },
        ]

        it('returns null for empty array', () => {
            expect(findQueryAtCursor([], 5)).toBeNull()
        })

        it('returns the query when cursor is inside it', () => {
            expect(findQueryAtCursor(queries, 0)).toBe(queries[0])
            expect(findQueryAtCursor(queries, 5)).toBe(queries[0])
            expect(findQueryAtCursor(queries, 8)).toBe(queries[0])
            expect(findQueryAtCursor(queries, 10)).toBe(queries[1])
            expect(findQueryAtCursor(queries, 15)).toBe(queries[1])
            expect(findQueryAtCursor(queries, 25)).toBe(queries[2])
        })

        it('returns nearest preceding query when cursor is between queries', () => {
            expect(findQueryAtCursor(queries, 9)).toBe(queries[0])
            expect(findQueryAtCursor(queries, 19)).toBe(queries[1])
        })

        it('returns last query when cursor is past the end', () => {
            expect(findQueryAtCursor(queries, 50)).toBe(queries[2])
        })

        it('returns first query when cursor is before all queries', () => {
            const offsetQueries: QueryRange[] = [{ query: 'SELECT 1', start: 5, end: 13 }]
            expect(findQueryAtCursor(offsetQueries, 0)).toBe(offsetQueries[0])
        })
    })

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
