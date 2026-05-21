import { dataColorVars } from 'lib/colors'

import { autoAssignBreakdownColors, BreakdownValueAndType } from './dashboardBreakdownColors'

describe('autoAssignBreakdownColors', () => {
    const valuesFromNames = (names: string[]): BreakdownValueAndType[] =>
        names.map((breakdownValue) => ({ breakdownValue, breakdownType: 'event' }))

    it('is deterministic for the same input', () => {
        const values = valuesFromNames(['Alibaba', 'Google', 'Amazon', 'Meta'])
        const first = autoAssignBreakdownColors(values)
        const second = autoAssignBreakdownColors(values)
        expect(first).toEqual(second)
    })

    it('produces no collisions when value count <= palette size', () => {
        const names = Array.from({ length: dataColorVars.length }, (_, i) => `value-${i}`)
        const out = autoAssignBreakdownColors(valuesFromNames(names))
        const tokens = out.map((c) => c.colorToken)
        expect(new Set(tokens).size).toBe(tokens.length)
        expect(tokens).toHaveLength(dataColorVars.length)
    })

    it('does not shift existing assignments when a lexically-later value is appended', () => {
        // extractBreakdownValues feeds us deterministically-sorted input,
        // so appending a value that sorts AFTER all existing ones must not
        // change colors for the existing values.
        const initial = valuesFromNames(['Alibaba', 'Amazon', 'Google', 'Meta'])
        const extended = [...initial, { breakdownValue: 'Stripe', breakdownType: 'event' as const }]

        const initialOut = autoAssignBreakdownColors(initial)
        const extendedOut = autoAssignBreakdownColors(extended)

        for (let i = 0; i < initial.length; i++) {
            expect(extendedOut[i].breakdownValue).toBe(initialOut[i].breakdownValue)
            expect(extendedOut[i].colorToken).toBe(initialOut[i].colorToken)
        }
    })

    it('skips null/undefined breakdown values', () => {
        const values: BreakdownValueAndType[] = [
            { breakdownValue: 'Alibaba', breakdownType: 'event' },
            { breakdownValue: null as any, breakdownType: 'event' },
            { breakdownValue: 'Google', breakdownType: 'event' },
        ]
        const out = autoAssignBreakdownColors(values)
        expect(out).toHaveLength(2)
        expect(out.map((c) => c.breakdownValue)).toEqual(['Alibaba', 'Google'])
    })

    it('still assigns all values when count exceeds palette size (allows reuse)', () => {
        const names = Array.from({ length: dataColorVars.length + 5 }, (_, i) => `value-${i}`)
        const out = autoAssignBreakdownColors(valuesFromNames(names))
        expect(out).toHaveLength(dataColorVars.length + 5)
        // every assignment is a valid preset
        out.forEach((c) => expect(c.colorToken).toMatch(/^preset-\d+$/))
    })
})
