import { MAX_NESTING_DEPTH, formatHogQL } from './formatHogQL'

describe('formatHogQL', () => {
    it('keeps HogQL-only syntax and the case of every token', () => {
        const query =
            "select properties.$browser, toStartOfDay(timestamp) as day, f'hi {event}' as greeting, a ?? b, c =~ 'x', any(d) from events where {filters} and {variables.n} = 1 // note"

        const { formatted } = formatHogQL(query)

        expect(formatted).toEqual(
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
            ].join('\n')
        )
        expect(formatHogQL(formatted ?? '').formatted).toEqual(formatted)
    })

    it('follows the editor indentation settings', () => {
        expect(formatHogQL('SELECT 1', { tabWidth: 2 }).formatted).toEqual('SELECT\n  1')
        expect(formatHogQL('SELECT 1', { useTabs: true }).formatted).toEqual('SELECT\n\t1')
    })

    it.each([
        ['a query that does not parse', "SELECT 'unterminated FROM events", 'unparsable'],
        [
            'a query nested too deeply to format quickly',
            `SELECT ${'('.repeat(MAX_NESTING_DEPTH + 1)}1${')'.repeat(MAX_NESTING_DEPTH + 1)}`,
            'too_large',
        ],
        ['a string prefix the formatter would split from its quote', "SELECT E'\\n' FROM events", 'unsupported'],
    ])('refuses %s', (_name, query, failure) => {
        expect(formatHogQL(query)).toEqual({ formatted: null, failure })
    })
})
