import { lifecycleOpIdFromEvent, uuidFromDistinctId } from '~/ingestion/common/persons/person-uuid'

jest.setTimeout(5000) // 5 sec timeout

describe('uuidFromDistinctId', () => {
    it('generates deterministic UUIDs', () => {
        expect(uuidFromDistinctId(1, 'test')).toMatchInlineSnapshot(`"246f7a43-5507-564f-b687-793ee3c2dd79"`)
        expect(uuidFromDistinctId(2, 'test')).toMatchInlineSnapshot(`"00ce873a-549c-548e-bbec-cc804a385dd8"`)
        expect(uuidFromDistinctId(1, 'test2')).toMatchInlineSnapshot(`"45c17302-ee44-5596-916a-0eba21f4b638"`)
    })
})

describe('lifecycleOpIdFromEvent', () => {
    it('is deterministic per event and scoped per team', () => {
        expect(lifecycleOpIdFromEvent(1, 'event-uuid')).toBe(lifecycleOpIdFromEvent(1, 'event-uuid'))
        expect(lifecycleOpIdFromEvent(1, 'event-uuid')).not.toBe(lifecycleOpIdFromEvent(2, 'event-uuid'))
        expect(lifecycleOpIdFromEvent(1, 'event-uuid')).not.toBe(lifecycleOpIdFromEvent(1, 'other-event'))
    })
})
