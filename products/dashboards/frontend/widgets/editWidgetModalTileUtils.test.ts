import {
    buildWidgetTileMetadataPatch,
    getWidgetEditModalTileDefaults,
    saveWidgetTileMetadataAfterConfig,
} from './editWidgetModalTileUtils'

describe('editWidgetModalTileUtils', () => {
    it('getWidgetEditModalTileDefaults returns empty strings when metadata is missing', () => {
        expect(getWidgetEditModalTileDefaults({})).toEqual({
            tileName: '',
            tileDescription: '',
        })
    })

    it('saveWidgetTileMetadataAfterConfig no-ops without onSaveMetadata', async () => {
        await expect(
            saveWidgetTileMetadataAfterConfig({ name: 'Old', description: 'Desc' }, 'New', 'Other')
        ).resolves.toBeUndefined()
    })

    it('buildWidgetTileMetadataPatch batches name and description changes', () => {
        expect(
            buildWidgetTileMetadataPatch(
                { name: 'Old', description: 'Old desc', defaultTitle: 'Top issues' },
                'New title',
                'New desc'
            )
        ).toEqual({ name: 'New title', description: 'New desc' })
    })

    it('saveWidgetTileMetadataAfterConfig clears name when it matches default title', async () => {
        const onSaveMetadata = jest.fn().mockResolvedValue(undefined)

        await saveWidgetTileMetadataAfterConfig(
            { name: 'Custom', defaultTitle: 'Untitled', onSaveMetadata },
            'Untitled',
            'Desc'
        )

        expect(onSaveMetadata).toHaveBeenCalledWith({ name: '', description: 'Desc' })
    })
})
