import { ParquetExtensionField, shouldShowParquetExtensionField } from './common'

describe('shouldShowParquetExtensionField', () => {
    const savedParquet = { file_format: 'Parquet', compression: 'zstd' }
    const shown = { isNew: false, fileFormat: 'Parquet', compression: 'zstd', savedConfig: savedParquet }

    it.each([
        ['a new export has nothing to grandfather', { ...shown, isNew: true }],
        ['the export has not loaded yet', { ...shown, savedConfig: null }],
        [
            'the export has only ever written JSON Lines',
            { ...shown, savedConfig: { file_format: 'JSONLines', compression: 'gzip' } },
        ],
        [
            'the export has only ever written uncompressed Parquet',
            { ...shown, savedConfig: { file_format: 'Parquet', compression: null } },
        ],
        [
            'the export already opted in to the standard extension',
            { ...shown, savedConfig: { ...savedParquet, legacy_parquet_extension: false } },
        ],
        ['the format is being switched away from Parquet', { ...shown, fileFormat: 'JSONLines' }],
        ['compression is being turned off, so the name carries no codec either way', { ...shown, compression: null }],
    ])('is false when %s', (_, props) => {
        expect(shouldShowParquetExtensionField(props)).toBe(false)
    })

    it.each([
        ['the flag has not been stamped yet', savedParquet],
        ['the flag is explicitly on', { ...savedParquet, legacy_parquet_extension: true }],
    ])('is true for a grandfathered Parquet export when %s', (_, savedConfig) => {
        expect(shouldShowParquetExtensionField({ ...shown, savedConfig })).toBe(true)
    })

    // Called directly rather than rendered, because the LemonField body needs a surrounding kea form.
    it('decides whether the field renders', () => {
        expect(ParquetExtensionField({ ...shown, isNew: true })).toBeNull()
        expect(ParquetExtensionField(shown)).not.toBeNull()
    })
})
