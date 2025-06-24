import { toUtcOffsetFormat } from './WebAnalyticsTile'

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
