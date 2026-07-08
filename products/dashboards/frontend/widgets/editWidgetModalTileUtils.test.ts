import { buildWidgetTileMetadataPatch, getWidgetEditModalTileDefaults } from './editWidgetModalBuilders'

describe('editWidgetModalBuilders tile metadata', () => {
    it('getWidgetEditModalTileDefaults returns empty strings when metadata is missing', () => {
        expect(getWidgetEditModalTileDefaults({})).toEqual({
            tileName: '',
            tileDescription: '',
        })
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

    it('buildWidgetTileMetadataPatch returns empty object when nothing changed', () => {
        expect(
            buildWidgetTileMetadataPatch(
                { name: 'Same', description: 'Same desc', defaultTitle: 'Untitled' },
                'Same',
                'Same desc'
            )
        ).toEqual({})
    })

    it('buildWidgetTileMetadataPatch clears name when it matches default title', () => {
        expect(buildWidgetTileMetadataPatch({ name: 'Custom', defaultTitle: 'Untitled' }, 'Untitled', 'Desc')).toEqual({
            name: '',
            description: 'Desc',
        })
    })
})
