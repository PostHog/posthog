import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { ExportedAssetType } from '~/types'

import { downloadExportedAsset } from './exporter'

const getResponse = jest.fn()

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        getResponse: (...args: any[]) => getResponse(...args),
        exports: {
            determineExportUrl: jest.fn((id: number) => `/api/environments/1/exports/${id}/content?download=true`),
        },
    },
}))

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: { error: jest.fn() },
}))

describe('downloadExportedAsset', () => {
    let fakeAnchor: HTMLAnchorElement
    let appendSpy: jest.SpyInstance
    let removeSpy: jest.SpyInstance

    beforeEach(() => {
        fakeAnchor = { style: {}, click: jest.fn() } as unknown as HTMLAnchorElement
        jest.spyOn(document, 'createElement').mockReturnValue(fakeAnchor)
        appendSpy = jest.spyOn(document.body, 'appendChild').mockImplementation((node) => node)
        removeSpy = jest.spyOn(document.body, 'removeChild').mockImplementation((node) => node)
    })

    afterEach(() => {
        jest.restoreAllMocks()
        getResponse.mockReset()
        ;(lemonToast.error as jest.Mock).mockReset()
    })

    it('navigates via anchor once the content endpoint responds successfully', async () => {
        // Cancelable body so we don't buffer large files in memory before the streaming download.
        const cancel = jest.fn().mockResolvedValue(undefined)
        getResponse.mockResolvedValue({ body: { cancel } })

        const result = await downloadExportedAsset({ id: 123 } as ExportedAssetType)

        expect(result).toBe(true)
        expect(getResponse).toHaveBeenCalledWith('/api/environments/1/exports/123/content?download=true')
        expect(cancel).toHaveBeenCalled()
        expect((fakeAnchor as any).href).toBe('/api/environments/1/exports/123/content?download=true')
        expect((fakeAnchor as any).click).toHaveBeenCalled()
        expect(appendSpy).toHaveBeenCalledWith(fakeAnchor)
        expect(removeSpy).toHaveBeenCalledWith(fakeAnchor)
    })

    it('shows an error toast and does not navigate when retrieval fails', async () => {
        // A failed content retrieval (e.g. an access-control 404) must not navigate the tab to the raw
        // JSON error — that renders as a blank/black page. It should surface a toast instead.
        getResponse.mockRejectedValue(new Error('Not found.'))

        const result = await downloadExportedAsset({ id: 123 } as ExportedAssetType)

        expect(result).toBe(false)
        expect((fakeAnchor as any).click).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalledWith('Export download failed: Not found.')
    })
})
