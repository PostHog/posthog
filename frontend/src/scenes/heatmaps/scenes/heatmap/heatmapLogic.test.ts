import { HeatmapType } from '~/types'

import { resolveHeatmapExportUrl } from './heatmapLogic'

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
