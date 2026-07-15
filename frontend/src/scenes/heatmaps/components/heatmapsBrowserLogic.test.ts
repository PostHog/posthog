import { normalizeHeatmapDataUrl } from './heatmapsBrowserLogic'

describe('normalizeHeatmapDataUrl', () => {
    it.each([
        ['example.com', null],
        ['   ', null],
        ['', null],
        [null, null],
        ['h', null],
        ['https://', null],
        ['https://example.com', { href: 'https://example.com/', matchType: 'exact' }],
        ['https://example.com/pricing', { href: 'https://example.com/pricing', matchType: 'exact' }],
        ['  https://example.com/pricing  ', { href: 'https://example.com/pricing', matchType: 'exact' }],
        ['https://example.com/users/*', { href: 'https://example.com/users/*', matchType: 'pattern' }],
    ] as const)('normalizeHeatmapDataUrl(%s) → %s', (input, expected) => {
        expect(normalizeHeatmapDataUrl(input)).toEqual(expected)
    })
})
