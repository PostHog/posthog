import {
    columnMaxContentLength,
    normalizeIdentifier,
    parseQueryTablesAndColumns,
    queryUsesFiltersPlaceholder,
} from './sql-utils'

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

    describe('queryUsesFiltersPlaceholder', () => {
        test.each([
            ['plain placeholder', 'SELECT * FROM events WHERE {filters}', true],
            ['field placeholder', 'SELECT * FROM events WHERE {filters.properties}', true],
            ['column-bound placeholder', 'SELECT * FROM v WHERE {filters(day AS timestamp)}', true],
            ['line-commented placeholder', 'SELECT * FROM events\n-- {filters}', false],
            ['inline line-commented placeholder', 'SELECT * FROM events -- WHERE {filters}', false],
            ['block-commented placeholder', 'SELECT * FROM events /* WHERE {filters} */', false],
            ['single-quoted placeholder', "SELECT '{filters}' FROM events", false],
            ['double-quoted placeholder', 'SELECT "{filters}" FROM events', false],
            ['backtick-quoted placeholder', 'SELECT `{filters}` FROM events', false],
            ['real placeholder after comment', 'SELECT * FROM events -- {filters}\nWHERE {filters}', true],
            ['real placeholder after block comment', 'SELECT * FROM events /* {filters} */ WHERE {filters}', true],
        ])('%s', (_name, query, expected) => {
            expect(queryUsesFiltersPlaceholder(query)).toBe(expected)
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

    describe('columnMaxContentLength', () => {
        it('returns the widest cell length in the column', () => {
            const rows = [['a'], ['abc'], ['ab']]
            expect(columnMaxContentLength(rows, 0, 0)).toBe(3)
        })

        it('never returns less than the header length', () => {
            const rows = [['a'], ['ab']]
            expect(columnMaxContentLength(rows, 0, 10)).toBe(10)
        })

        it('treats null and undefined cells as length 0 and stringifies non-strings', () => {
            const rows = [[null], [undefined], [12345]]
            expect(columnMaxContentLength(rows, 0, 0)).toBe(5)
        })

        it('does not throw on result sets near the 50,000-row HogQL cap', () => {
            const rows = Array.from({ length: 50000 }, () => ['x'])
            expect(() => columnMaxContentLength(rows, 0, 0)).not.toThrow()
            expect(columnMaxContentLength(rows, 0, 0)).toBe(1)
        })
    })
})
