import { normalizeTickLabelRotation } from './axis-labels'

describe('axis label utilities', () => {
    it.each([
        ['positive rotation', 45, 45],
        ['negative rotation', -45, -45],
        ['positive overflow', 120, 90],
        ['negative overflow', -120, -90],
        ['NaN', Number.NaN, 0],
        ['positive infinity', Number.POSITIVE_INFINITY, 0],
        ['negative infinity', Number.NEGATIVE_INFINITY, 0],
    ])('normalizes %s', (_name, rotation, expected) => {
        expect(normalizeTickLabelRotation(rotation)).toBe(expected)
    })
})
