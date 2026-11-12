import { ApiError } from 'lib/api-error'

import { FileUploadFormat } from './fileUploadSource'
import {
    FILE_UPLOAD_TOO_LARGE_MESSAGE,
    MAX_FILE_UPLOAD_SIZE_BYTES,
    fileFormatMismatchError,
    fileUploadErrorMessage,
    fileUploadFormErrors,
} from './fileUploadSourceLogic'

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
    it('points to the bucket sources instead of self-managed tables', () => {
        const file = new File(['a'], 'big.csv')
        Object.defineProperty(file, 'size', { value: MAX_FILE_UPLOAD_SIZE_BYTES + 1 })
        const errors = fileUploadFormErrors({ files: [file], table_name: 'my_table', file_format: 'csv' })
        expect(errors.files).toContain('Amazon S3, Google Cloud Storage, Azure Blob Storage or Cloudflare R2')
        expect(errors.files).not.toContain('self-managed')
    })

    it.each<[string, ApiError, string]>([
        [
            'a gateway 413 with no body',
            new ApiError('Non-OK response [POST /api/projects/1/warehouse_tables/upload_file/] (status 413: )', 413),
            FILE_UPLOAD_TOO_LARGE_MESSAGE,
        ],
        [
            'a server message',
            new ApiError('Failed to upload file', 400, undefined, { message: 'Failed to upload file' }),
            'Failed to upload file',
        ],
    ])('shows a readable upload error for %s', (_, error, expected) => {
        expect(fileUploadErrorMessage(error, 'Could not upload the file.')).toEqual(expected)
    })
})
