import { getQueryAtCursor, splitSqlQueries } from './sql-utils'

describe('splitSqlQueries', () => {
    it.each([
        {
            name: 'single query without semicolon',
            input: 'SELECT 1',
            expected: [{ query: 'SELECT 1', startOffset: 0, endOffset: 8 }],
        },
        {
            name: 'single query with trailing semicolon',
            input: 'SELECT 1;',
            expected: [
                { query: 'SELECT 1', startOffset: 0, endOffset: 9 },
                { query: '', startOffset: 9, endOffset: 9 },
            ],
        },
        {
            name: 'two queries',
            input: 'SELECT 1;\nSELECT 2',
            expected: [
                { query: 'SELECT 1', startOffset: 0, endOffset: 9 },
                { query: 'SELECT 2', startOffset: 9, endOffset: 18 },
            ],
        },
        {
            name: 'two queries with blank lines between',
            input: 'SELECT 1;\n\nSELECT 2',
            expected: [
                { query: 'SELECT 1', startOffset: 0, endOffset: 9 },
                { query: 'SELECT 2', startOffset: 9, endOffset: 19 },
            ],
        },
        {
            name: 'three queries with trailing semicolon',
            input: 'SELECT 1;\nSELECT 2;\nSELECT 3;',
            expected: [
                { query: 'SELECT 1', startOffset: 0, endOffset: 9 },
                { query: 'SELECT 2', startOffset: 9, endOffset: 19 },
                { query: 'SELECT 3', startOffset: 19, endOffset: 29 },
                { query: '', startOffset: 29, endOffset: 29 },
            ],
        },
        {
            name: 'two queries on the same line',
            input: 'SELECT 1; SELECT 2',
            expected: [
                { query: 'SELECT 1', startOffset: 0, endOffset: 9 },
                { query: 'SELECT 2', startOffset: 9, endOffset: 18 },
            ],
        },
        {
            name: 'semicolon inside single-quoted string',
            input: "SELECT 'hello;world'",
            expected: [{ query: "SELECT 'hello;world'", startOffset: 0, endOffset: 20 }],
        },
        {
            name: 'semicolon inside double-quoted identifier',
            input: 'SELECT "col;name" FROM t',
            expected: [{ query: 'SELECT "col;name" FROM t', startOffset: 0, endOffset: 24 }],
        },
        {
            name: 'semicolon inside backtick-quoted identifier',
            input: 'SELECT `col;name` FROM t',
            expected: [{ query: 'SELECT `col;name` FROM t', startOffset: 0, endOffset: 24 }],
        },
        {
            name: 'semicolon inside line comment',
            input: 'SELECT 1 -- comment; still comment\nFROM t',
            expected: [{ query: 'SELECT 1 -- comment; still comment\nFROM t', startOffset: 0, endOffset: 41 }],
        },
        {
            name: 'semicolon inside block comment',
            input: 'SELECT /* comment; */ 1',
            expected: [{ query: 'SELECT /* comment; */ 1', startOffset: 0, endOffset: 23 }],
        },
        {
            name: 'escaped single quote in string',
            input: "SELECT 'it\\'s;fine';\nSELECT 2",
            expected: [
                { query: "SELECT 'it\\'s;fine'", startOffset: 0, endOffset: 20 },
                { query: 'SELECT 2', startOffset: 20, endOffset: 29 },
            ],
        },
        {
            name: 'doubled single quote escape in string',
            input: "SELECT 'it''s;fine';\nSELECT 2",
            expected: [
                { query: "SELECT 'it''s;fine'", startOffset: 0, endOffset: 20 },
                { query: 'SELECT 2', startOffset: 20, endOffset: 29 },
            ],
        },
        {
            name: 'empty input',
            input: '',
            expected: [{ query: '', startOffset: 0, endOffset: 0 }],
        },
        {
            name: 'just a semicolon',
            input: ';',
            expected: [
                { query: '', startOffset: 0, endOffset: 1 },
                { query: '', startOffset: 1, endOffset: 1 },
            ],
        },
        {
            name: 'multiline query with block comment across lines',
            input: 'SELECT /*\n;\n*/ 1;\nSELECT 2',
            expected: [
                { query: 'SELECT /*\n;\n*/ 1', startOffset: 0, endOffset: 17 },
                { query: 'SELECT 2', startOffset: 17, endOffset: 26 },
            ],
        },
    ])('$name', ({ input, expected }) => {
        const result = splitSqlQueries(input)
        expect(result.map(({ query, startOffset, endOffset }) => ({ query, startOffset, endOffset }))).toEqual(expected)
    })

    it('computes correct line/column positions', () => {
        const result = splitSqlQueries('SELECT 1;\nSELECT 2')
        expect(result[0]).toMatchObject({ startLine: 1, startColumn: 1, endLine: 1, endColumn: 10 })
        expect(result[1]).toMatchObject({ startLine: 1, startColumn: 10, endLine: 2, endColumn: 9 })
    })

    it('computes correct line/column for multiline queries', () => {
        const result = splitSqlQueries('SELECT\n  1;\nSELECT\n  2')
        expect(result[0]).toMatchObject({ startLine: 1, startColumn: 1, endLine: 2, endColumn: 5 })
        expect(result[1]).toMatchObject({ startLine: 2, startColumn: 5, endLine: 4, endColumn: 4 })
    })
})

describe('getQueryAtCursor', () => {
    it.each([
        {
            name: 'cursor in first query',
            input: 'SELECT 1;\nSELECT 2',
            cursorOffset: 4,
            expected: 'SELECT 1',
        },
        {
            name: 'cursor in second query',
            input: 'SELECT 1;\nSELECT 2',
            cursorOffset: 14,
            expected: 'SELECT 2',
        },
        {
            name: 'cursor at semicolon (belongs to preceding query)',
            input: 'SELECT 1;\nSELECT 2',
            cursorOffset: 8,
            expected: 'SELECT 1',
        },
        {
            name: 'cursor right after semicolon (belongs to preceding query)',
            input: 'SELECT 1;\nSELECT 2',
            cursorOffset: 9,
            expected: 'SELECT 1',
        },
        {
            name: 'cursor at start of next line after semicolon',
            input: 'SELECT 1;\nSELECT 2',
            cursorOffset: 10,
            expected: 'SELECT 2',
        },
        {
            name: 'single query, cursor in middle',
            input: 'SELECT 1',
            cursorOffset: 3,
            expected: 'SELECT 1',
        },
        {
            name: 'cursor right after trailing semicolon (belongs to preceding query)',
            input: 'SELECT 1;',
            cursorOffset: 9,
            expected: 'SELECT 1',
        },
        {
            name: 'cursor on blank line between queries',
            input: 'SELECT 1;\n\nSELECT 2',
            cursorOffset: 10,
            expected: 'SELECT 2',
        },
        {
            name: 'empty input returns null',
            input: '',
            cursorOffset: 0,
            expected: null,
        },
    ])('$name', ({ input, cursorOffset, expected }) => {
        expect(getQueryAtCursor(input, cursorOffset)).toBe(expected)
    })
})
