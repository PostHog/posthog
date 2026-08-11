import { scrollDepthColor } from './ScrollDepthCanvas'

describe('scrollDepthColor', () => {
    // Recording-backed scroll depth is one viewport tall, so cumulative reach barely drops.
    // Scaling against the visible range (min..max) rather than the top bucket keeps a gradient.
    const maxCount = 100
    const minCount = 90

    it('spreads near-max counts across distinct colors instead of a flat wash', () => {
        const top = scrollDepthColor(100, maxCount, minCount, 'default')
        const middle = scrollDepthColor(95, maxCount, minCount, 'default')
        const deepest = scrollDepthColor(90, maxCount, minCount, 'default')

        expect(new Set([top, middle, deepest]).size).toBe(3)
    })

    it('paints the most-reached band red and the least-reached band blue', () => {
        expect(scrollDepthColor(maxCount, maxCount, minCount, 'default')).toBe('hsl(0, 100%, 50%)')
        expect(scrollDepthColor(minCount, maxCount, minCount, 'default')).toBe('hsl(260, 100%, 50%)')
    })

    it('does not divide by zero when every band has the same count', () => {
        expect(scrollDepthColor(50, 50, 50, 'default')).toBe('hsl(0, 100%, 50%)')
    })

    it('normalizes palette opacity over the visible range', () => {
        expect(scrollDepthColor(maxCount, maxCount, minCount, 'red')).toBe('rgba(255, 0, 0, 1)')
        expect(scrollDepthColor(minCount, maxCount, minCount, 'red')).toBe('rgba(255, 0, 0, 0)')
    })
})
