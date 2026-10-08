import { ApiConfig } from 'lib/api'

import { ExportedAssetType } from '~/types'

import { downloadExportedAsset, exportedAssetBlob } from './exporter'

const getResponse = jest.fn()

jest.mock('lib/api', () => {
    const actual = jest.requireActual('lib/api')
    return {
        ...actual,
        __esModule: true,
        default: {
            ...actual.default,
            getResponse: (...args: any[]) => getResponse(...args),
        },
    }
})

describe('exporter', () => {
    let fakeAnchor: HTMLAnchorElement
    let appendSpy: jest.SpyInstance
    let removeSpy: jest.SpyInstance

    beforeEach(() => {
        ApiConfig.setCurrentTeamId(1)
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
        expect((fakeAnchor as any).href).toBe('/api/projects/1/exports/123/content?download=true')
        expect((fakeAnchor as any).click).toHaveBeenCalled()
        expect(appendSpy).toHaveBeenCalledWith(fakeAnchor)

        // Removal is deferred — removing the anchor synchronously can cancel the download in Firefox.
        expect(removeSpy).not.toHaveBeenCalled()
        jest.runOnlyPendingTimers()
        expect(removeSpy).toHaveBeenCalledWith(fakeAnchor)
    })

    it('fetches the bytes for the editor without following the object storage redirect', async () => {
        getResponse.mockResolvedValue({ blob: async () => new Blob(['png']) })

        await exportedAssetBlob({ id: 123 } as ExportedAssetType)

        expect(getResponse).toHaveBeenCalledWith('/api/projects/1/exports/123/content?direct=true')
    })
})
