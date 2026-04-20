import { buildQueryForColumnClick, normalizeIdentifier, parseQueryTablesAndColumns } from './sql-utils'

describe('sql-utils', () => {
    describe('normalizeIdentifier', () => {
        test.each([
            ['plain identifier is lowercased', 'Events', 'events'],
            ['backtick-quoted identifier is stripped and lowercased', '`MyTable`', 'mytable'],
            ['double-quoted identifier is stripped and lowercased', '"MyColumn"', 'mycolumn'],
            ['single-quoted identifier is stripped and lowercased', "'MyField'", 'myfield'],
            ['already lowercase plain identifier is unchanged', 'events', 'events'],
            ['identifier with underscores is lowercased', 'My_Table', 'my_table'],
        ])('%s', (_name, input, expected) => {
            expect(normalizeIdentifier(input)).toEqual(expected)
        })
    })

    describe('buildQueryForColumnClick', () => {
        it('returns fallback query when currentQuery is null', async () => {
            const result = await buildQueryForColumnClick(null, 'events', 'id')
            expect(result).toEqual('SELECT id FROM events LIMIT 100')
        })

        it('replaces star with clicked column when select is star-only', async () => {
            const result = await buildQueryForColumnClick('SELECT * FROM events LIMIT 100', 'events', 'id')
            expect(result).toEqual('SELECT id FROM events LIMIT 100')
        })

        it('removes column that is already in the select list (toggle off)', async () => {
            const result = await buildQueryForColumnClick('SELECT id, name FROM events LIMIT 100', 'events', 'id')
            expect(result).toEqual('SELECT name FROM events LIMIT 100')
        })

        it('appends new column to existing columns', async () => {
            const result = await buildQueryForColumnClick('SELECT id FROM events LIMIT 100', 'events', 'name')
            expect(result).toEqual('SELECT id, name FROM events LIMIT 100')
        })

        it('falls back to star when removing the only remaining column', async () => {
            const result = await buildQueryForColumnClick('SELECT id FROM events LIMIT 100', 'events', 'id')
            expect(result).toEqual('SELECT "*" FROM events LIMIT 100')
        })

        it('returns fallback query when table in query differs from clicked table', async () => {
            const result = await buildQueryForColumnClick('SELECT * FROM persons LIMIT 100', 'events', 'id')
            expect(result).toEqual('SELECT id FROM events LIMIT 100')
        })

        it('preserves LIMIT from the existing query', async () => {
            const result = await buildQueryForColumnClick('SELECT * FROM events LIMIT 50', 'events', 'id')
            expect(result).toEqual('SELECT id FROM events LIMIT 50')
        })

        it('preserves LIMIT and OFFSET from the existing query', async () => {
            const result = await buildQueryForColumnClick('SELECT * FROM events LIMIT 100 OFFSET 20', 'events', 'id')
            expect(result).toEqual('SELECT id FROM events LIMIT 100 OFFSET 20')
        })

        it('handles a JOIN query and matches against the first table', async () => {
            const result = await buildQueryForColumnClick(
                'SELECT * FROM events JOIN persons ON events.id = persons.id LIMIT 100',
                'events',
                'id'
            )
            expect(result).toEqual('SELECT id FROM events LIMIT 100')
        })

        it('returns fallback query for invalid SQL', async () => {
            const result = await buildQueryForColumnClick('NOT VALID SQL', 'events', 'id')
            expect(result).toEqual('SELECT id FROM events LIMIT 100')
        })

        it('uses default LIMIT 100 when query has no LIMIT', async () => {
            const result = await buildQueryForColumnClick('SELECT * FROM events', 'events', 'id')
            expect(result).toEqual('SELECT id FROM events LIMIT 100')
        })
    })

    describe('parseQueryTablesAndColumns', () => {
        it('returns empty object for null queryInput', async () => {
            expect(await parseQueryTablesAndColumns(null)).toEqual({})
        })

        it('returns star column for SELECT * FROM events', async () => {
            const result = await parseQueryTablesAndColumns('SELECT * FROM events')
            expect(result).toEqual({ events: { '*': true } })
        })

        it('maps bare columns to their table', async () => {
            const result = await parseQueryTablesAndColumns('SELECT id, name FROM users')
            expect(result).toEqual({ users: { id: true, name: true } })
        })

        it('assigns table-qualified column to the correct table', async () => {
            const result = await parseQueryTablesAndColumns('SELECT users.id FROM users')
            expect(result).toEqual({ users: { id: true } })
        })

        it('returns empty object for invalid SQL', async () => {
            const result = await parseQueryTablesAndColumns('NOT VALID SQL')
            expect(result).toEqual({})
        })

        it('handles star with JOIN — both tables get star', async () => {
            const result = await parseQueryTablesAndColumns(
                'SELECT * FROM events JOIN persons ON events.id = persons.id'
            )
            expect(result).toEqual({
                events: { '*': true },
                persons: { '*': true },
            })
        })

        it('handles mixed star and named columns', async () => {
            const result = await parseQueryTablesAndColumns('SELECT *, id FROM events')
            expect(result).toEqual({ events: { '*': true, id: true } })
        })
    })
})
