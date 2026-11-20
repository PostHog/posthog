import { spreadLabels } from './spreadLabels'

describe('spreadLabels', () => {
    const MIN_GAP = 2
    const MIN = 0
    const MAX = 200

    // On a short-lived issue both pills want the same x. Without the second right-to-left pass the
    // clamp at `max` piles them back on top of each other.
    it.each([
        {
            name: 'identical centers',
            items: [
                { center: 100, halfWidth: 25 },
                { center: 100, halfWidth: 25 },
            ],
            expected: [100, 152],
        },
        {
            name: 'both pinned at the right edge',
            items: [
                { center: 200, halfWidth: 30 },
                { center: 198, halfWidth: 30 },
            ],
            expected: [170, 108],
        },
        {
            name: 'both pinned at the left edge',
            items: [
                { center: 0, halfWidth: 30 },
                { center: 2, halfWidth: 30 },
            ],
            expected: [30, 92],
        },
        {
            name: 'three crowded labels',
            items: [
                { center: 90, halfWidth: 28 },
                { center: 100, halfWidth: 28 },
                { center: 110, halfWidth: 28 },
            ],
            expected: [56, 114, 172],
        },
    ])('separates $name', ({ items, expected }) => {
        expect(spreadLabels(items, MIN_GAP, MIN, MAX)).toEqual(expected)
    })

    it('spills the leftmost labels past `min` when they cannot all fit', () => {
        const items = [
            { center: 100, halfWidth: 60 },
            { center: 100, halfWidth: 60 },
            { center: 100, halfWidth: 60 },
        ]
        expect(spreadLabels(items, MIN_GAP, MIN, MAX)).toEqual([-104, 18, 140])
    })
})
