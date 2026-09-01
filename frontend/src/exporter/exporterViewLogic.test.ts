import { heatmapScreenshotFetchOptions } from './exporterViewLogic'

describe('heatmapScreenshotFetchOptions', () => {
    it.each([
        [
            'includes credentials for a same-origin absolute URL',
            'http://localhost/api/environments/1/heatmap_screenshots/2/content/',
            true,
        ],
        [
            'includes credentials for a same-origin relative URL',
            '/api/environments/1/heatmap_screenshots/2/content/',
            true,
        ],
        ['omits credentials for a cross-origin URL', 'https://example.com/collect', false],
    ])('%s', (_name, url, includesCredentials) => {
        const options = heatmapScreenshotFetchOptions(url, 'renderer-token')

        expect(options.headers).toEqual(includesCredentials ? { Authorization: 'Bearer renderer-token' } : undefined)
    })
})
