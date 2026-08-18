import { mergeOpIdFromRequest, uuidFromDistinctId } from '~/ingestion/common/persons/person-uuid'

jest.setTimeout(5000) // 5 sec timeout

describe('uuidFromDistinctId', () => {
    it('generates deterministic UUIDs', () => {
        expect(uuidFromDistinctId(1, 'test')).toMatchInlineSnapshot(`"246f7a43-5507-564f-b687-793ee3c2dd79"`)
        expect(uuidFromDistinctId(2, 'test')).toMatchInlineSnapshot(`"00ce873a-549c-548e-bbec-cc804a385dd8"`)
        expect(uuidFromDistinctId(1, 'test2')).toMatchInlineSnapshot(`"45c17302-ee44-5596-916a-0eba21f4b638"`)
    })
})

describe('mergeOpIdFromRequest', () => {
    it('separates a fold from the single-source merges it falls back to', () => {
        // The saga freezes the request behind this key and rejects any later
        // call presenting it with a different source list, so sharing one key
        // between the two shapes loses the fallback merge entirely.
        const fold = mergeOpIdFromRequest(1, 'event-uuid', ['anon-1', 'anon-2'], 10_000)
        const single = mergeOpIdFromRequest(1, 'event-uuid', ['anon-1'], 10_000)
        expect(fold).not.toEqual(single)
    })

    it('gives different move limits different keys', () => {
        // skipped_move_limit is a recorded verdict; the async re-attempt's
        // whole purpose is a raised limit, so it must be a fresh op rather
        // than attach to the skip. Same-limit retries keep replaying.
        expect(mergeOpIdFromRequest(1, 'event-uuid', ['anon-1'], 10_000)).not.toEqual(
            mergeOpIdFromRequest(1, 'event-uuid', ['anon-1'], 50_000)
        )
    })

    it('gives differently ordered source lists different keys', () => {
        // Source order is property precedence, and the saga compares its
        // frozen request in order: one key for two orders would make the
        // second call a permanent FAILED_PRECONDITION instead of a fresh
        // op that converges as a no-op.
        expect(mergeOpIdFromRequest(1, 'event-uuid', ['anon-2', 'anon-1'], 10_000)).not.toEqual(
            mergeOpIdFromRequest(1, 'event-uuid', ['anon-1', 'anon-2'], 10_000)
        )
    })

    it('cannot collide two source lists that join to one string', () => {
        // Distinct ids are arbitrary customer strings; without length
        // prefixes, ['a,b'] and ['a','b'] would share a key and the second
        // merge would be refused as a replay of the first.
        expect(mergeOpIdFromRequest(1, 'event-uuid', ['a,b'], 10_000)).not.toEqual(
            mergeOpIdFromRequest(1, 'event-uuid', ['a', 'b'], 10_000)
        )
    })

    it('scopes the key per team', () => {
        expect(mergeOpIdFromRequest(1, 'event-uuid', ['anon-1'], 10_000)).not.toEqual(
            mergeOpIdFromRequest(2, 'event-uuid', ['anon-1'], 10_000)
        )
    })
})
