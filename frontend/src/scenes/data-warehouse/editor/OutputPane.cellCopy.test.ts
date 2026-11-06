import { extractGridCellValue } from './OutputPane'

describe('extractGridCellValue', () => {
    it('returns the stringified value for a normal data cell', () => {
        expect(extractGridCellValue('name', { name: 'All_callers' })).toBe('All_callers')
        expect(extractGridCellValue('count', { count: 42 })).toBe('42')
    })

    it('returns null for the details column so it falls through to the native menu', () => {
        expect(extractGridCellValue('__details', { __details: 'anything' })).toBeNull()
    })

    it('returns null for null, undefined, and empty-string values', () => {
        expect(extractGridCellValue('name', { name: null })).toBeNull()
        expect(extractGridCellValue('name', {})).toBeNull()
        expect(extractGridCellValue('name', { name: '' })).toBeNull()
    })

    it('returns null for HogQLX-shaped values instead of copying the raw AST', () => {
        // These render as rich content; copying String(value) would put the internal AST on the clipboard.
        expect(extractGridCellValue('url', { url: '["__hx_tag", "a", {"href": "https://posthog.com"}]' })).toBeNull()
    })

    it('still copies a plain string that merely mentions __hx_tag', () => {
        expect(extractGridCellValue('note', { note: 'contains ["__hx_tag" midway' })).toBe(
            'contains ["__hx_tag" midway'
        )
    })
})
