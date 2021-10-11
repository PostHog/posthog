import { cleanMetadataValues } from 'scenes/insights/InsightMetadata/utils'

describe('cleanMetadataValues()', () => {
    it('handles empty input', () => {
        expect(cleanMetadataValues({})).toEqual({})
        expect(cleanMetadataValues({ filters: {} })).toEqual({ filters: {} })
        expect(cleanMetadataValues({ refreshing: true })).toEqual({ refreshing: true })
        expect(cleanMetadataValues({ description: undefined })).toEqual({ description: null })
        expect(cleanMetadataValues({ color: null })).toEqual({ color: null })
    })
    it('handles blank strings as expected', () => {
        expect(cleanMetadataValues({ name: '' })).toEqual({ name: null })
        expect(cleanMetadataValues({ description: '  ' })).toEqual({ description: null })
    })
})
