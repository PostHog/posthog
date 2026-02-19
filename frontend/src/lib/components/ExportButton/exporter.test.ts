import { ExportedAssetType } from '~/types'

import { downloadExportedAsset } from './exporter'

jest.mock('lib/api', () => ({
    exports: {
        determineExportUrl: jest.fn((id: number) => `/api/environments/1/exports/${id}/content?download=true`),
    },
}))

describe('downloadExportedAsset', () => {
    let appendChildSpy: jest.SpyInstance
    let removeChildSpy: jest.SpyInstance
    let clickSpy: jest.Mock

    beforeEach(() => {
        clickSpy = jest.fn()
        appendChildSpy = jest.spyOn(document.body, 'appendChild').mockImplementation((node) => node)
        removeChildSpy = jest.spyOn(document.body, 'removeChild').mockImplementation((node) => node)
        jest.spyOn(document, 'createElement').mockReturnValue({
            style: {},
            click: clickSpy,
        } as unknown as HTMLAnchorElement)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('uses anchor navigation instead of fetch to avoid buffering large files in memory', () => {
        const asset = { id: 123 } as ExportedAssetType

        downloadExportedAsset(asset)

        const anchor = document.createElement('a') as unknown as Record<string, unknown>
        expect(anchor['href']).toBe('/api/environments/1/exports/123/content?download=true')
        expect(appendChildSpy).toHaveBeenCalled()
        expect(clickSpy).toHaveBeenCalled()
        expect(removeChildSpy).toHaveBeenCalled()
    })
})
