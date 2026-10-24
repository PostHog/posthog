import { comparisonTooltipText, toUtcOffsetFormat, viewportFilterValue } from './WebAnalyticsTile'

describe('WebAnalyticsTile helpers', () => {
    describe('toUtcOffsetFormat', () => {
        it.each([
            [0, 'UTC'],
            [0.25, 'UTC+0:15'],
            [1, 'UTC+1'],
            [1.5, 'UTC+1:30'],
            [-0, 'UTC'],
            [-0.25, 'UTC-0:15'],
            [-1, 'UTC-1'],
            [-1.5, 'UTC-1:30'],
        ])('should format %d to %s', (minutes, expected) => {
            expect(toUtcOffsetFormat(minutes)).toEqual(expected)
        })
    })

    describe('comparisonTooltipText', () => {
        const formatNumber = (value: number): string => `${value}`

        it.each([
            [10, 0, true, 'Increased from 0 to 10 since last period'],
            [10, 5, true, 'Increased by 100% since last period (from 5 to 10)'],
            [5, 10, true, 'Decreased by 50% since last period (from 10 to 5)'],
            [5, 5, true, 'No change since last period (5)'],
            [10, null, true, null],
            [10, 5, false, null],
        ])('formats %s compared with %s', (current, previous, compare, expected) => {
            expect(comparisonTooltipText(current, previous, compare, formatNumber)).toEqual(expected)
        })
    })
})

describe('viewportFilterValue', () => {
    it('builds the filter for a viewport pair', () => {
        expect(viewportFilterValue([1920, 1080])).toBe('1920x1080')
    })

    it('offers no filter for the (not set) pair', () => {
        expect(viewportFilterValue([null, null])).toBeUndefined()
    })
})
