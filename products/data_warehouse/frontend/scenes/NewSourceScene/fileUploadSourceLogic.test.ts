import { FileUploadFormat } from './fileUploadSource'
import { fileFormatMismatchError, fileUploadFormErrors } from './fileUploadSourceLogic'

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
