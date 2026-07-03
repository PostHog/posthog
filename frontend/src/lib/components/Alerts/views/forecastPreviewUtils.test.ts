import { findFirstCrossing } from './forecastPreviewUtils'

describe('findFirstCrossing', () => {
    // The returned index drives both the chart marker and the "predicted to cross" summary date —
    // an off-by-one here desyncs the two. Covers upper/lower-only, no crossing, and boundary indices.
    it.each([
        ['upper-only crossing', [1, 2, 6, 3], { upper: 5 }, 2],
        ['lower-only crossing', [4, 3, -1, 2], { lower: 0 }, 2],
        ['both bounds set, crosses upper first', [1, 6, -5, 2], { lower: 0, upper: 5 }, 1],
        ['both bounds set, crosses lower first', [1, -1, 6, 2], { lower: 0, upper: 5 }, 1],
        ['no crossing', [1, 2, 3, 4], { lower: 0, upper: 5 }, null],
        ['crossing at index 0', [6, 1, 2, 3], { upper: 5 }, 0],
        ['crossing at the last index', [1, 2, 3, 6], { upper: 5 }, 3],
        ['no bounds set', [1, 2, 3], {}, null],
        ['empty forecast', [], { upper: 5 }, null],
    ] as const)('%s', (_, forecastYhat, bounds, expected) => {
        expect(findFirstCrossing([...forecastYhat], bounds)).toBe(expected)
    })

    it('returns null bounds unchanged', () => {
        expect(findFirstCrossing([1, 2, 3], null)).toBeNull()
    })
})
