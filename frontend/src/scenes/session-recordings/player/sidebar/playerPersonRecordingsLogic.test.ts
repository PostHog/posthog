import { RecordingsQueryResponse } from '~/queries/schema/schema-general'
import { SessionRecordingType } from '~/types'

import { mergeRecordingPage } from './playerPersonRecordingsLogic'

describe('playerPersonRecordingsLogic', () => {
    const rec = (id: string): SessionRecordingType => ({ id }) as SessionRecordingType
    const page = (ids: string[], overrides: Partial<RecordingsQueryResponse> = {}): RecordingsQueryResponse => ({
        results: ids.map(rec),
        has_next: false,
        ...overrides,
    })

    it('appends the next page onto the accumulated results and keeps the new page cursor', () => {
        const previous = page(['a', 'b'], { has_next: true, next_cursor: 'cursor-1' })
        const next = page(['c', 'd'], { has_next: false, next_cursor: undefined })

        const merged = mergeRecordingPage(previous, next)

        // guards against "Load older" replacing instead of appending, which silently drops earlier recordings
        expect(merged.results.map((r) => r.id)).toEqual(['a', 'b', 'c', 'd'])
        expect(merged.has_next).toBe(false)
        expect(merged.next_cursor).toBeUndefined()
    })

    it('treats a null previous page as an empty accumulator', () => {
        const merged = mergeRecordingPage(null, page(['a', 'b'], { has_next: true, next_cursor: 'cursor-1' }))

        expect(merged.results.map((r) => r.id)).toEqual(['a', 'b'])
        expect(merged.has_next).toBe(true)
    })
})
