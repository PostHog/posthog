import { durationSeconds, parseDuration } from './duration'

describe('duration', () => {
    // The grammar is shared by every duration a workflow expresses, so loosening it in one place
    // silently changes delays, wait ceilings and conversion windows together.
    it.each([
        ['7d', { amount: 7, unit: 'd', negative: false }],
        ['1.5h', { amount: 1.5, unit: 'h', negative: false }],
        ['.5m', { amount: 0.5, unit: 'm', negative: false }],
        ['45s', { amount: 45, unit: 's', negative: false }],
        ['0d', { amount: 0, unit: 'd', negative: false }],
        ['-45d', { amount: 45, unit: 'd', negative: true }],
    ])('parses %p', (value, expected) => {
        expect(parseDuration(value)).toEqual(expected)
    })

    it.each([
        [''],
        ['5'],
        ['d'],
        // Case and whitespace stay out: a delay reading `5 d` as five days would be a wait nobody wrote.
        ['5D'],
        ['5 d'],
        [' 5d'],
        ['5d '],
        ['5days'],
        ['1.2.3d'],
        ['1e3d'],
        ['--5d'],
        ['+5d'],
        ['1,5d'],
        ['5w'],
        // Non-ASCII digits parse under some number readers but not this one.
        ['٥d'],
    ])('rejects %p', (value) => {
        expect(parseDuration(value)).toBeNull()
    })

    it.each([
        ['7d', 604800],
        ['12h', 43200],
        ['90m', 5400],
        ['45s', 45],
    ])('converts %p to seconds', (value, expected) => {
        expect(durationSeconds(value)).toBe(expected)
    })

    it('refuses a signed duration', () => {
        // Only a `delay_until` offset may point backwards. A negative wait or conversion window is
        // meaningless, and reading one as positive would schedule work in the past.
        expect(durationSeconds('-7d')).toBeNull()
        expect(parseDuration('-7d')).toEqual({ amount: 7, unit: 'd', negative: true })
    })

    it('applies no ceiling of its own', () => {
        // The per-unit ceilings belong to delays. Applying `d: 30` here would cut a 365-day
        // conversion window to 30 days without saying so.
        expect(durationSeconds('365d')).toBe(365 * 86400)
    })
})
