import { resolveHeatmapExportUrl } from './heatmapLogic'

describe('resolveHeatmapExportUrl', () => {
    const origin = 'https://us.posthog.com'

    it('resolves screenshot API paths to absolute URLs so SSRF validation accepts them', () => {
        const screenshotUrl = '/api/environments/1/heatmap_screenshots/42/content/?width=1400'

        expect(resolveHeatmapExportUrl('screenshot', screenshotUrl, 'https://example.com/page', origin)).toBe(
            `${origin}${screenshotUrl}`
        )
    })

    it('returns the display URL unchanged for iframe-type heatmaps', () => {
        expect(
            resolveHeatmapExportUrl(
                'iframe',
                '/api/environments/1/heatmap_screenshots/42/content/',
                'https://example.com/page',
                origin
            )
        ).toBe('https://example.com/page')
    })

    it('returns an empty string for screenshot heatmaps without a screenshotUrl', () => {
        expect(resolveHeatmapExportUrl('screenshot', null, 'https://example.com/page', origin)).toBe('')
    })

    it('returns an empty string for iframe heatmaps without a displayUrl', () => {
        expect(resolveHeatmapExportUrl('iframe', '/api/something', null, origin)).toBe('')
    })

    it('preserves an already-absolute screenshot URL', () => {
        const absolute = 'https://another.posthog.com/api/environments/1/heatmap_screenshots/42/content/'

        expect(resolveHeatmapExportUrl('screenshot', absolute, null, origin)).toBe(absolute)
    })
})
