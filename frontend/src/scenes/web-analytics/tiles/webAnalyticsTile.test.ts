import { toUtcOffsetFormat, viewportFilterValue } from './WebAnalyticsTile'

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

describe('viewportFilterValue', () => {
    it('builds the filter for a viewport pair', () => {
        expect(viewportFilterValue([1920, 1080])).toBe('1920x1080')
    })

    it('offers no filter for the (not set) pair', () => {
        expect(viewportFilterValue([null, null])).toBeUndefined()
    })
})
