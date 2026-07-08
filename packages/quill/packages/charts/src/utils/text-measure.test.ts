import { ELLIPSIS, MAX_CATEGORY_LABEL_WIDTH, measureLabelWidth, truncateToWidth } from './text-measure'

describe('truncateToWidth', () => {
    const longUrl = 'https://app.posthog.com/project/1/insights/abc123/edit?with=a&very=long&query=string'

    it('returns the original string when it already fits', () => {
        expect(truncateToWidth('short', MAX_CATEGORY_LABEL_WIDTH)).toBe('short')
    })

    it('returns the original string for a non-positive max width', () => {
        expect(truncateToWidth(longUrl, 0)).toBe(longUrl)
        expect(truncateToWidth(longUrl, -10)).toBe(longUrl)
    })

    it('truncates with a trailing ellipsis and fits within the budget', () => {
        // Derive the budget from the actual measured width so the assertion holds regardless of the
        // canvas measurement backend (real canvas vs jsdom mock vs SSR fallback).
        const budget = measureLabelWidth(longUrl) / 2
        const result = truncateToWidth(longUrl, budget)
        expect(result).not.toBe(longUrl)
        expect(result.endsWith(ELLIPSIS)).toBe(true)
        expect(result.length).toBeLessThan(longUrl.length)
        expect(measureLabelWidth(result)).toBeLessThanOrEqual(budget)
    })

    it('collapses to a bare ellipsis when the budget is narrower than the ellipsis', () => {
        const ellipsisWidth = measureLabelWidth(ELLIPSIS)
        expect(truncateToWidth(longUrl, ellipsisWidth - 0.01)).toBe(ELLIPSIS)
    })
})
