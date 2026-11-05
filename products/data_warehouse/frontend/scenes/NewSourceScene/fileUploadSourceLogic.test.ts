import { FileUploadFormat } from './fileUploadSource'
import { MAX_FILE_UPLOAD_SIZE_BYTES, fileFormatMismatchError, fileUploadFormErrors } from './fileUploadSourceLogic'

describe('file upload format validation', () => {
    it.each<[string, FileUploadFormat]>([
        ['data.xlsx', 'csv'],
        ['data.xls', 'json'],
        ['report.numbers', 'parquet'],
    ])('rejects spreadsheet file %s regardless of selected format', (filename, format) => {
        expect(fileFormatMismatchError(filename, format)).toContain('Spreadsheet files')
    })

    it('flags a file whose extension belongs to a different supported format', () => {
        expect(fileFormatMismatchError('events.json', 'csv')).toContain('looks like a JSON file')
    })

    it.each<[string, FileUploadFormat]>([
        ['events.csv', 'csv'],
        ['events.ndjson', 'json'],
        ['events.parquet', 'parquet'],
    ])('accepts %s when the matching format is selected', (filename, format) => {
        expect(fileFormatMismatchError(filename, format)).toBeUndefined()
    })

    it('leaves an unrecognized extension alone so a valid file is not blocked', () => {
        // A CSV exported as .txt is still parseable; we only block confident mismatches.
        expect(fileFormatMismatchError('export.txt', 'csv')).toBeUndefined()
    })

    it('surfaces the mismatch as a files error so submission is blocked', () => {
        const file = new File(['a,b'], 'sheet.xlsx')
        const errors = fileUploadFormErrors({ files: [file], table_name: 'my_table', file_format: 'csv' })
        expect(errors.files).toContain('Spreadsheet files')
    })
})

describe('oversized file message', () => {
    it.each([
        { enabled: false, expected: 'as a self-managed source instead', unexpected: 'Amazon S3' },
        {
            enabled: true,
            expected: 'Amazon S3, Google Cloud Storage, Azure Blob Storage or Cloudflare R2',
            unexpected: 'self-managed',
        },
    ])('points to the right bucket source when managed object storage sources enabled=$enabled', (c) => {
        const file = new File(['a'], 'big.csv')
        Object.defineProperty(file, 'size', { value: MAX_FILE_UPLOAD_SIZE_BYTES + 1 })
        const errors = fileUploadFormErrors({ files: [file], table_name: 'my_table', file_format: 'csv' }, c.enabled)
        expect(errors.files).toContain(c.expected)
        expect(errors.files).not.toContain(c.unexpected)
    })
})
