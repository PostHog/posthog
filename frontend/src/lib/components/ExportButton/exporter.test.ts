import { ExportedAssetType } from '~/types'

import { downloadExportedAsset } from './exporter'

jest.mock('lib/api', () => ({
    exports: {
        determineExportUrl: jest.fn((id: number) => `/api/environments/1/exports/${id}/content?download=true`),
    },
}))

describe('downloadExportedAsset', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('uses anchor navigation instead of fetch to avoid buffering large files in memory', () => {
        const fakeAnchor = { style: {}, click: jest.fn() } as unknown as HTMLAnchorElement
        jest.spyOn(document, 'createElement').mockReturnValue(fakeAnchor)
        const appendSpy = jest.spyOn(document.body, 'appendChild').mockImplementation((node) => node)
        const removeSpy = jest.spyOn(document.body, 'removeChild').mockImplementation((node) => node)

        downloadExportedAsset({ id: 123 } as ExportedAssetType)

        expect((fakeAnchor as any).href).toBe('/api/environments/1/exports/123/content?download=true')
        expect(appendSpy).toHaveBeenCalledWith(fakeAnchor)
        expect((fakeAnchor as any).click).toHaveBeenCalled()
        expect(removeSpy).toHaveBeenCalledWith(fakeAnchor)
    })
})
