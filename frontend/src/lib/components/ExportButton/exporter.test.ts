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

describe('downloadExportedAsset', () => {
    let fakeAnchor: HTMLAnchorElement
    let appendSpy: jest.SpyInstance
    let removeSpy: jest.SpyInstance

    beforeEach(() => {
        jest.useFakeTimers()
        fakeAnchor = { style: {}, click: jest.fn() } as unknown as HTMLAnchorElement
        jest.spyOn(document, 'createElement').mockReturnValue(fakeAnchor)
        appendSpy = jest.spyOn(document.body, 'appendChild').mockImplementation((node) => node)
        removeSpy = jest.spyOn(document.body, 'removeChild').mockImplementation((node) => node)
    })

    afterEach(() => {
        jest.runOnlyPendingTimers()
        jest.useRealTimers()
        jest.restoreAllMocks()
        getResponse.mockReset()
    })

    it('navigates via a synchronous anchor click with no preflight fetch', () => {
        downloadExportedAsset({ id: 123 } as ExportedAssetType)

        // The click must fire synchronously with no await before it (no preflight fetch), or Safari
        // drops the download once the user gesture expires.
        expect(getResponse).not.toHaveBeenCalled()
        expect((fakeAnchor as any).href).toBe('/api/environments/1/exports/123/content?download=true')
        expect((fakeAnchor as any).click).toHaveBeenCalled()
        expect(appendSpy).toHaveBeenCalledWith(fakeAnchor)

        // Removal is deferred — removing the anchor synchronously can cancel the download in Firefox.
        expect(removeSpy).not.toHaveBeenCalled()
        jest.runOnlyPendingTimers()
        expect(removeSpy).toHaveBeenCalledWith(fakeAnchor)
    })
})
