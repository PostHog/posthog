import { MAX_NESTING_DEPTH, formatHogQL } from './formatHogQL'

describe('formatHogQL', () => {
    it.each([
        [
            'HogQL-only syntax and the case of every token',
            "select properties.$browser, toStartOfDay(timestamp) as day, f'hi {event}' as greeting, a ?? b, c =~ 'x', any(d) from events where {filters} and {variables.n} = 1 // note",
            [
                'select',
                '    properties.$browser,',
                '    toStartOfDay(timestamp) as day,',
                "    f'hi {event}' as greeting,",
                '    a ?? b,',
                "    c =~ 'x',",
                '    any(d)',
                'from',
                '    events',
                'where',
                '    {filters}',
                '    and {variables.n} = 1 // note',
            ],
        ],
        [
            'every statement and a query commented out after the last one',
            'select 1; select event from events;\n-- select 2;',
            ['select', '    1;', '', 'select', '    event', 'from', '    events;', '', '-- select 2;'],
        ],
    ])('keeps %s', async (_name, query, lines) => {
        const { formatted } = await formatHogQL(query)

        expect(formatted).toEqual(lines.join('\n'))
        expect((await formatHogQL(formatted ?? '')).formatted).toEqual(formatted)
    })

    it('follows the editor indentation settings', async () => {
        expect((await formatHogQL('SELECT 1', { tabWidth: 2 })).formatted).toEqual('SELECT\n  1')
        expect((await formatHogQL('SELECT 1', { useTabs: true })).formatted).toEqual('SELECT\n\t1')
    })

    it.each([
        ['a query that does not parse', "SELECT 'unterminated FROM events", 'unparsable'],
        [
            'a query nested too deeply to format quickly',
            `SELECT ${'('.repeat(MAX_NESTING_DEPTH + 1)}1${')'.repeat(MAX_NESTING_DEPTH + 1)}`,
            'too_large',
        ],
        ['a string prefix the formatter would split from its quote', "SELECT E'\\n' FROM events", 'unsupported'],
        [
            'a literal in a template string expression that the formatter would change',
            "SELECT f'{concat(' a  b ')}'",
            'unsupported',
        ],
        ['a HogQLX tag that the formatter would split', 'select <Sparkline data={[1,2,3]} />', 'unsupported'],
    ])('refuses %s', async (_name, query, failure) => {
        expect(await formatHogQL(query)).toEqual({ formatted: null, failure })
    })
})
