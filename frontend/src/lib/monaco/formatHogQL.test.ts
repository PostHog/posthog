import { formatHogQL } from './formatHogQL'

describe('formatHogQL', () => {
    it('formats a simple SELECT', () => {
        const out = formatHogQL('select event,count() from events group by event')
        expect(out).toContain('SELECT')
        expect(out).toContain('FROM')
        expect(out).toContain('GROUP BY')
        expect(out.split('\n').length).toBeGreaterThan(1)
    })

    it('returns empty input unchanged', () => {
        expect(formatHogQL('')).toBe('')
        expect(formatHogQL('   ')).toBe('   ')
    })

    it('preserves HogQL property accessor', () => {
        const out = formatHogQL('select person.properties.email from events')
        expect(out).toContain('person.properties.email')
    })

    it('falls through on parse failure', () => {
        const broken = 'select from where ((('
        expect(() => formatHogQL(broken)).not.toThrow()
    })
})
