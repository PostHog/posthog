import { findQueryAtCursor, findStatementAtOffset, type QueryRange, splitQueries } from 'lib/monaco/multiQueryUtils'

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

    describe('findStatementAtOffset', () => {
        const input = 'SELECT 1;\n  SELECT 2 '

        it.each<[string, number, string | null]>([
            ['cursor inside a statement', 16, '\n  SELECT 2 '],
            ['cursor after a trailing space', 21, '\n  SELECT 2 '],
            ['cursor on the separator', 8, 'SELECT 1'],
            ['cursor directly after the separator', 9, '\n  SELECT 2 '],
        ])('%s', (_, cursorOffset, expected) => {
            expect(findStatementAtOffset(input, cursorOffset)?.query ?? null).toBe(expected)
        })

        it('returns null when the segment holds no statement text', () => {
            expect(findStatementAtOffset('SELECT 1;\n', 10)).toBeNull()
        })

        it('keeps offsets rebasable onto the returned statement', () => {
            const statement = findStatementAtOffset(input, 21)!
            expect(input.slice(statement.start, statement.end)).toBe(statement.query)
            expect(21 - statement.start).toBe(statement.query.length)
        })
    })
})
