import { ParquetExtensionField, shouldShowParquetExtensionField } from './common'

describe('shouldShowParquetExtensionField', () => {
    const savedParquet = { file_format: 'Parquet' }

    it.each([
        ['a new export has nothing to grandfather', { isNew: true, fileFormat: 'Parquet', savedConfig: savedParquet }],
        ['the export has not loaded yet', { isNew: false, fileFormat: 'Parquet', savedConfig: null }],
        [
            'the export has only ever written JSON Lines',
            { isNew: false, fileFormat: 'Parquet', savedConfig: { file_format: 'JSONLines' } },
        ],
        [
            'the export already opted in to the standard extension',
            { isNew: false, fileFormat: 'Parquet', savedConfig: { ...savedParquet, legacy_parquet_extension: false } },
        ],
        [
            'the format is being switched away from Parquet',
            { isNew: false, fileFormat: 'JSONLines', savedConfig: savedParquet },
        ],
    ])('is false when %s', (_, props) => {
        expect(shouldShowParquetExtensionField(props)).toBe(false)
    })

    it.each([
        ['the flag has not been stamped yet', savedParquet],
        ['the flag is explicitly on', { ...savedParquet, legacy_parquet_extension: true }],
    ])('is true for a grandfathered Parquet export when %s', (_, savedConfig) => {
        expect(shouldShowParquetExtensionField({ isNew: false, fileFormat: 'Parquet', savedConfig })).toBe(true)
    })

    // Called directly rather than rendered, because the LemonField body needs a surrounding kea form.
    it('decides whether the field renders', () => {
        expect(ParquetExtensionField({ isNew: true, fileFormat: 'Parquet', savedConfig: savedParquet })).toBeNull()
        expect(ParquetExtensionField({ isNew: false, fileFormat: 'Parquet', savedConfig: savedParquet })).not.toBeNull()
    })
})
