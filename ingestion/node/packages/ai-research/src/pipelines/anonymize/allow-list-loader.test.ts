import { buildAllowLists, loadAllowLists } from './allow-list-loader'

describe('anonymize/allow-list-loader', () => {
    describe('buildAllowLists', () => {
        it('builds lists from a well-formed document', () => {
            const lists = buildAllowLists({ text: ['Keepme'], url: ['Segment'] })
            // Looked up case-insensitively.
            expect(lists.textContains('keepme')).toBe(true)
            expect(lists.urlContains('segment')).toBe(true)
            expect(lists.textContains('other')).toBe(false)
        })

        it('filters non-string entries and tolerates missing fields', () => {
            const lists = buildAllowLists({ text: ['ok', 42, null, { a: 1 }] as unknown[] })
            expect(lists.textContains('ok')).toBe(true)
            // Missing url field → empty url list (over-redaction, the safe direction).
            expect(lists.urlContains('anything')).toBe(false)
        })

        it('coerces a garbage document to empty lists rather than throwing', () => {
            const lists = buildAllowLists({ text: 'not-an-array' as unknown as unknown[] })
            expect(lists.textContains('the')).toBe(false)
        })
    })

    describe('loadAllowLists', () => {
        it('returns the in-binary defaults when no fetcher is configured', async () => {
            const lists = await loadAllowLists(undefined)
            // A default stopword is present.
            expect(lists.textContains('the')).toBe(true)
        })

        it('uses the fetched lists on success', async () => {
            const lists = await loadAllowLists(() => Promise.resolve({ text: ['customword'], url: [] }))
            expect(lists.textContains('customword')).toBe(true)
            // The fetched list replaces (does not merge with) the defaults.
            expect(lists.textContains('the')).toBe(false)
        })

        it('FAILS SAFE: a fetch error falls back to defaults, never to no scrubbing', async () => {
            const lists = await loadAllowLists(() => Promise.reject(new Error('s3 unavailable')))
            // Defaults are restored, so scrubbing stays enabled.
            expect(lists.textContains('the')).toBe(true)
        })
    })
})
