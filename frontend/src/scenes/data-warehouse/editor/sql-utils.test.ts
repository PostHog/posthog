import {
    buildSidebarColumnInsert,
    normalizeIdentifier,
    parseQueryTablesAndColumns,
    queryUsesFiltersPlaceholder,
} from './sql-utils'

describe('sql-utils', () => {
    describe('buildSidebarColumnInsert', () => {
        test('a column click in a blank editor scaffolds a full SELECT ... FROM ...', () => {
            expect(
                buildSidebarColumnInsert({
                    columnText: 'created_at',
                    tableName: 'cable_riser',
                    fullText: '',
                    cursorOffset: 0,
                })
            ).toEqual({
                text: 'SELECT created_at\nFROM cable_riser',
                replaceWholeQuery: true,
                cursorOffsetInText: 17,
            })
        })

        test('whitespace-only editor is still treated as blank', () => {
            const result = buildSidebarColumnInsert({
                columnText: 'id',
                tableName: 'cable_riser',
                fullText: '\n  \n',
                cursorOffset: 0,
            })
            expect(result.replaceWholeQuery).toBe(true)
        })

        test('a bare column with no table cannot scaffold, so it inserts as-is', () => {
            expect(
                buildSidebarColumnInsert({
                    columnText: 'id',
                    tableName: null,
                    fullText: '',
                    cursorOffset: 0,
                })
            ).toEqual({ text: 'id', replaceWholeQuery: false, cursorOffsetInText: 2 })
        })

        // The `|` in each query marks the cursor; it is stripped and its index becomes the offset.
        // `expected` is the text inserted, so a comma separates two columns and a space keeps a
        // clause keyword such as FROM from taking an invalid leading comma.
        test.each([
            ['appending after a column adds a comma', 'SELECT id|', ', created_at'],
            ['a following column keeps a comma on each side', 'SELECT id, |name FROM t', 'created_at, '],
            ['a column before a keyword gets a comma before and a space after', 'SELECT id |FROM t', ', created_at '],
            ['a column right after SELECT takes no comma but stays separated', 'SELECT |id FROM t', 'created_at, '],
            ['no leading comma right after SELECT keyword', 'SELECT |', 'created_at'],
            ['a following FROM is separated by a space, never a comma', 'SELECT |FROM t', 'created_at '],
            ['an existing comma before the cursor is not doubled', 'SELECT id,| FROM t', 'created_at'],
            ['inside a function call takes no separators', 'SELECT count(|) FROM t', 'created_at'],
            ['a dotted prefix is completed without a comma', 'SELECT events.|', 'created_at'],
            ['a closing quote before the cursor still gets a comma', 'SELECT properties."a.b"|', ', created_at'],
        ])('%s', (_name, query, expectedText) => {
            const cursorOffset = query.indexOf('|')
            const fullText = query.replace('|', '')
            const result = buildSidebarColumnInsert({
                columnText: 'created_at',
                tableName: 'cable_riser',
                fullText,
                cursorOffset,
            })
            expect(result.text).toBe(expectedText)
            expect(result.replaceWholeQuery).toBe(false)
        })
    })

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
})
