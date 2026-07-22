import type { MacroApi } from '../../generated/api.schemas'
import { macroToDoc } from './applyMacro'

function macro(overrides: Partial<MacroApi>): MacroApi {
    return {
        id: '1',
        short_id: 'abc',
        name: 'Test',
        created_at: '2026-01-01T00:00:00Z',
        created_by: {} as MacroApi['created_by'],
        ...overrides,
    }
}

describe('macroToDoc', () => {
    it('uses stored rich_content when present', () => {
        const rich = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'rich body' }] }] }
        expect(macroToDoc(macro({ rich_content: rich, content: 'plain fallback' }))).toEqual(rich)
    })

    // Regression: macros created via the API (or imported) have only plain-text `content` and no
    // rich_content. Without this fallback the editor renders blank and saving wipes the reply.
    it('falls back to plain-text content, one paragraph per line', () => {
        const doc = macroToDoc(macro({ rich_content: {}, content: 'line one\nline two' }))
        expect(doc).toEqual({
            type: 'doc',
            content: [
                { type: 'paragraph', content: [{ type: 'text', text: 'line one' }] },
                { type: 'paragraph', content: [{ type: 'text', text: 'line two' }] },
            ],
        })
    })

    // The canonical empty TipTap doc has a one-paragraph content array; it must not be treated as
    // real rich content, or it would render blank and mask the plain-text fallback.
    it('treats an empty rich_content doc as blank and falls back to content', () => {
        const emptyDoc = { type: 'doc', content: [{ type: 'paragraph', content: [] }] }
        const doc = macroToDoc(macro({ rich_content: emptyDoc, content: 'from content' }))
        expect(doc).toEqual({
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'from content' }] }],
        })
    })

    it('returns an empty paragraph when there is no content at all', () => {
        expect(macroToDoc(macro({ rich_content: {}, content: '' }))).toEqual({
            type: 'doc',
            content: [{ type: 'paragraph', content: [] }],
        })
    })
})
