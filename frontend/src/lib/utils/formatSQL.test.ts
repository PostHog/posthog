import { formatSQL } from './formatSQL'

describe('formatSQL', () => {
    it('returns the original value for empty/whitespace input', () => {
        expect(formatSQL('')).toBe('')
        expect(formatSQL('   ')).toBe('   ')
    })

    it('indents a simple query and preserves keyword casing', () => {
        const result = formatSQL("select event, count() from events where event = '$pageview' group by event")
        expect(result).toBe(
            [
                'select',
                '    event,',
                '    count()',
                'from',
                '    events',
                'where',
                "    event = '$pageview'",
                'group by',
                '    event',
            ].join('\n')
        )
    })

    it('preserves HogQL property accessors with $-prefixed identifiers', () => {
        const result = formatSQL('SELECT properties.$current_url, count() FROM events')
        expect(result).toContain('properties.$current_url')
    })

    it('handles ClickHouse array literals and lambdas', () => {
        const result = formatSQL('SELECT arrayMap(x -> x*2, [1,2,3])')
        expect(result).toContain('arrayMap(x -> x * 2, [1, 2, 3])')
    })

    it('preserves backtick-quoted identifiers', () => {
        const result = formatSQL('select `person.properties.email` from events')
        expect(result).toContain('`person.properties.email`')
    })

    it('throws on syntactically broken input it cannot tokenize', () => {
        expect(() => formatSQL("select 'unterminated")).toThrow()
    })
})
