import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { exporterViewLogic, heatmapScreenshotFetchOptions } from './exporterViewLogic'
import { ExportType } from './types'

describe('heatmapScreenshotFetchOptions', () => {
    const originalFetch = global.fetch

    afterEach(() => {
        global.fetch = originalFetch
        jest.restoreAllMocks()
    })

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

    it('keeps credentials off the real screenshot fetch for a cross-origin URL', async () => {
        initKeaTests()
        const heatmapUrl = 'https://example.com/collect'
        global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404 } as Response)
        jest.spyOn(console, 'error').mockImplementation()
        const logic = exporterViewLogic.build({
            type: ExportType.Heatmap,
            exportToken: 'renderer-token',
            heatmap_url: heatmapUrl,
            heatmap_context: { heatmap_url: heatmapUrl, heatmap_type: 'screenshot' },
        })

        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ isLoading: false })
        logic.unmount()

        expect(global.fetch).toHaveBeenCalledWith(heatmapUrl, {})
    })
})
