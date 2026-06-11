import { getUploadedFile } from './fileUploads'

describe('getUploadedFile', () => {
    it('returns null when no file is present', () => {
        expect(getUploadedFile(undefined)).toBeNull()
        expect(getUploadedFile(null)).toBeNull()
        expect(getUploadedFile('')).toBeNull()
        expect(getUploadedFile([])).toBeNull()
        expect(getUploadedFile([{}])).toBeNull()
    })

    it('returns the first file for a non-empty upload field', () => {
        const file = new File(['{}'], 'service-account.json', { type: 'application/json' })
        expect(getUploadedFile([file])).toBe(file)
    })
})
