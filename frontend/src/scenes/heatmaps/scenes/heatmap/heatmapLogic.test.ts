import { HeatmapStatus, HeatmapType } from '~/types'

import { resolveHeatmapExportUrl, resolveScreenshotReadiness } from './heatmapLogic'

describe('heatmapLogic', () => {
    describe('resolveScreenshotReadiness', () => {
        // A 'completed' snapshot whose only stored bytes live in `content_location` (object storage)
        // is not fetchable - the content endpoint 501s on it. Regressing `has_content` back to counting
        // that as ready points the <img> at a URL guaranteed to fail, so this must resolve to
        // 'unavailable' (surface an error) rather than 'ready' (render) or 'pending' (poll forever).
        it.each([
            ['completed' as HeatmapStatus, true, 'ready'],
            ['completed' as HeatmapStatus, false, 'unavailable'],
            ['failed' as HeatmapStatus, false, 'failed'],
            ['failed' as HeatmapStatus, true, 'failed'],
            ['processing' as HeatmapStatus, false, 'pending'],
            ['processing' as HeatmapStatus, true, 'pending'],
        ] as const)('status=%s, hasContent=%s → %s', (status, hasContent, expected) => {
            expect(resolveScreenshotReadiness(status, hasContent)).toBe(expected)
        })
    })

    describe('resolveHeatmapExportUrl', () => {
        const origin = 'https://us.posthog.com'

        it.each([
            [
                'screenshot',
                '/api/environments/1/heatmap_screenshots/42/content/?width=1400',
                'https://example.com/page',
                `${origin}/api/environments/1/heatmap_screenshots/42/content/?width=1400`,
            ],
            [
                'iframe',
                '/api/environments/1/heatmap_screenshots/42/content/',
                'https://example.com/page',
                'https://example.com/page',
            ],
            ['screenshot', null, 'https://example.com/page', ''],
            ['iframe', '/api/something', null, ''],
            [
                'screenshot',
                'https://another.posthog.com/api/environments/1/heatmap_screenshots/42/content/',
                null,
                'https://another.posthog.com/api/environments/1/heatmap_screenshots/42/content/',
            ],
        ] as const)(
            'resolveHeatmapExportUrl(%s, screenshotUrl=%s, displayUrl=%s) → %s',
            (type, screenshotUrl, displayUrl, expected) => {
                expect(resolveHeatmapExportUrl(type as HeatmapType, screenshotUrl, displayUrl, origin)).toBe(expected)
            }
        )
    })
})
