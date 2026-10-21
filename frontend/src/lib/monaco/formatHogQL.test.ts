import { formatHogQL } from './formatHogQL'

describe('formatHogQL', () => {
    it('keeps HogQL-only syntax and the case of every token', () => {
        const query =
            "select properties.$browser, toStartOfDay(timestamp) as day, a ?? b, c =~ 'x', any(d) from events where {filters} and {variables.n} = 1 // note"

        const formatted = formatHogQL(query)

        expect(formatted).toEqual(
            [
                'select',
                '    properties.$browser,',
                '    toStartOfDay(timestamp) as day,',
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
        expect(formatHogQL(formatted ?? '')).toEqual(formatted)
    })

    it('follows the editor indentation settings', () => {
        expect(formatHogQL('SELECT 1', { tabWidth: 2 })).toEqual('SELECT\n  1')
        expect(formatHogQL('SELECT 1', { useTabs: true })).toEqual('SELECT\n\t1')
    })

    it('returns null for a query it cannot parse', () => {
        expect(formatHogQL("SELECT 'unterminated FROM events")).toBeNull()
    })
})
