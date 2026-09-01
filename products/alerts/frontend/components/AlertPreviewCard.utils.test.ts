import { getBreakdownPreviewSummary } from './AlertPreviewCard.utils'

describe('getBreakdownPreviewSummary', () => {
    it('includes the latest value from every breakdown series', () => {
        expect(
            getBreakdownPreviewSummary([
                { values: [20, 30, 40], relative: false },
                { values: [10, 20, 120], relative: false },
            ])
        ).toEqual({
            valueCount: 2,
            lowestValue: 40,
            highestValue: 120,
            relative: false,
        })
    })
})
