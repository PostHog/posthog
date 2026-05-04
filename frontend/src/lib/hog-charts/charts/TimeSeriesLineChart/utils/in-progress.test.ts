import type { Series } from '../../../core/types'
import { applyInProgressToSeries } from './in-progress'

const SERIES: Series[] = [
    { key: 'a', label: 'A', data: [1, 2, 3, 4] },
    { key: 'b', label: 'B', data: [5, 6, 7, 8] },
]

describe('applyInProgressToSeries', () => {
    it('returns the original reference when inProgress is undefined', () => {
        expect(applyInProgressToSeries(SERIES, undefined)).toBe(SERIES)
    })

    it('sets stroke.partial.fromIndex on each series when configured', () => {
        const result = applyInProgressToSeries(SERIES, { fromIndex: 2 })
        expect(result[0].stroke?.partial?.fromIndex).toBe(2)
        expect(result[1].stroke?.partial?.fromIndex).toBe(2)
    })

    it("preserves a series' explicit stroke.partial", () => {
        const explicitPartial = { fromIndex: 99, pattern: [4, 4] as number[] }
        const series: Series[] = [{ key: 'a', label: 'A', data: [1, 2, 3], stroke: { partial: explicitPartial } }]
        const result = applyInProgressToSeries(series, { fromIndex: 1 })
        expect(result[0].stroke?.partial).toBe(explicitPartial)
    })
})
