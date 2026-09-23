import {
    filtersPlaceholderBindings,
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

    describe('filtersPlaceholderBindings', () => {
        test.each([
            ['no placeholder', 'SELECT * FROM v', null],
            ['plain placeholder is not column-bound', 'SELECT * FROM events WHERE {filters}', null],
            ['single binding', 'SELECT * FROM v WHERE {filters(day AS timestamp)}', ['timestamp']],
            [
                'several bindings, one quoted',
                "SELECT * FROM v WHERE {filters(created_at AS timestamp, plan AS 'plan')}",
                ['timestamp', 'plan'],
            ],
            ['null opt-out still binds the key', 'SELECT * FROM v WHERE {filters(null AS timestamp)}', ['timestamp']],
            [
                'binding over a function call keeps the outer key',
                'SELECT * FROM v WHERE {filters(toDateTime(day, 0) AS timestamp)}',
                ['timestamp'],
            ],
            ['no timestamp binding', "SELECT * FROM v WHERE {filters(plan AS 'plan')}", ['plan']],
            ['commented-out placeholder', 'SELECT * FROM v -- {filters(day AS timestamp)}', null],
            ['key case is kept', 'SELECT * FROM v WHERE {filters(day AS Timestamp)}', ['Timestamp']],
        ])('%s', (_name, query, expected) => {
            expect(filtersPlaceholderBindings(query)).toEqual(expected)
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
