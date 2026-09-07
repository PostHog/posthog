import {
    normalizeIdentifier,
    parseQueryTablesAndColumns,
    queryUsesFiltersPlaceholder,
    queryUsesVariablesPlaceholder,
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
            ['slash-commented placeholder', 'SELECT * FROM events\n// {filters}', false],
            ['hash-commented placeholder', 'SELECT * FROM events\n# {filters}', false],
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

    describe('queryUsesVariablesPlaceholder', () => {
        test.each([
            ['field placeholder', 'SELECT * FROM events WHERE created_at > now() - {variables.days_count}', true],
            ['plain placeholder', 'SELECT {variables} FROM events', true],
            ['line-commented placeholder', 'SELECT * FROM events\n-- {variables.days_count}', false],
            ['slash-commented placeholder', 'SELECT * FROM events\n// {variables.days_count}', false],
            ['hash-commented placeholder', 'SELECT * FROM events\n# {variables.days_count}', false],
            ['single-quoted placeholder', "SELECT '{variables.days_count}' FROM events", false],
            ['block-commented placeholder', 'SELECT * FROM events /* {variables.days_count} */', false],
            ['no placeholder', 'SELECT * FROM events', false],
            ['positional reference is not a comment', 'SELECT #1, {variables.x} FROM events', true],
            ['real placeholder after comment', 'SELECT * FROM events -- {variables.x}\nWHERE {variables.y}', true],
        ])('%s', (_name, query, expected) => {
            expect(queryUsesVariablesPlaceholder(query)).toBe(expected)
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
