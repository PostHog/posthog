import { hasThresholdBounds, valueBreachesBounds } from './alertPreviewShared'

describe('alertPreviewShared', () => {
    it.each([
        ['no bounds object', null, false],
        ['undefined bounds', undefined, false],
        ['empty bounds', {}, false],
        ['lower only', { lower: 1 }, true],
        ['upper only', { upper: 1 }, true],
        ['both', { lower: 1, upper: 9 }, true],
    ])('hasThresholdBounds: %s', (_name, bounds, expected) => {
        expect(hasThresholdBounds(bounds as any)).toBe(expected)
    })

    it.each([
        ['null value never breaches', null, { lower: 50 }, false],
        ['no bounds never breaches', 5, null, false],
        ['below lower breaches', 5, { lower: 10 }, true],
        ['at lower is ok (strict <)', 10, { lower: 10 }, false],
        ['above upper breaches', 15, { upper: 10 }, true],
        ['at upper is ok (strict >)', 10, { upper: 10 }, false],
        ['within a lower+upper range is ok', 40, { lower: 10, upper: 80 }, false],
        ['above the upper of a range breaches', 90, { lower: 10, upper: 80 }, true],
    ])('valueBreachesBounds: %s', (_name, value, bounds, expected) => {
        expect(valueBreachesBounds(value as number | null, bounds as any)).toBe(expected)
    })
})
