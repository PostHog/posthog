import { formatCostUsd } from './formatCost'

describe('formatCostUsd', () => {
    it.each([
        [0, '$0'],
        [0.0004, '<$0.001'],
        [0.004, '$0.004'],
        [0.0021, '$0.0021'],
        [0.0154, '$0.0154'],
        [0.1257, '$0.1257'],
        [0.5, '$0.50'],
        [0.999, '$0.999'],
        [1.5, '$1.50'],
    ])('formats cost %p as %p', (cost, expected) => {
        expect(formatCostUsd(cost)).toBe(expected)
    })
})
