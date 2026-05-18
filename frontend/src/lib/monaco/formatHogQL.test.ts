import { formatHogQL } from './formatHogQL'

describe('formatHogQL', () => {
    it('formats a simple SELECT', () => {
        const out = formatHogQL('select event,count() from events group by event')
        expect(out).toContain('SELECT')
        expect(out).toContain('FROM')
        expect(out).toContain('GROUP BY')
        expect(out.split('\n').length).toBeGreaterThan(1)
    })

    it.each([
        ['empty string', ''],
        ['whitespace only', '   '],
        ['tab and newline only', '\t\n'],
    ])('returns %s unchanged', (_label, input) => {
        expect(formatHogQL(input)).toBe(input)
    })

    it('preserves HogQL property accessor', () => {
        const out = formatHogQL('select person.properties.email from events')
        expect(out).toContain('person.properties.email')
    })

    it.each([
        ['unbalanced parens', 'select from where ((('],
        ['stray keyword', 'select where group'],
        ['truncated expression', 'select * from events where event ='],
    ])('does not throw on %s', (_label, input) => {
        expect(() => formatHogQL(input)).not.toThrow()
    })
})
