import { LiveEvent } from '~/types'

import { deduplicateEvents } from './deduplicateEvents'

function makeEvent(uuid: string): LiveEvent {
    return {
        uuid,
        event: '$pageview',
        properties: {},
        timestamp: '2026-01-01T00:00:00Z',
        team_id: 1,
        distinct_id: 'user-1',
        created_at: '2026-01-01T00:00:00Z',
    }
}

describe('deduplicateEvents', () => {
    it('prepends new events and drops duplicates by uuid', () => {
        const state = [makeEvent('a')]
        const result = deduplicateEvents(state, [makeEvent('b'), makeEvent('a')], 10)
        expect(result.map((e) => e.uuid)).toEqual(['b', 'a'])
    })

    it('caps the result at the limit', () => {
        const state = [makeEvent('a'), makeEvent('b')]
        const result = deduplicateEvents(state, [makeEvent('c')], 2)
        expect(result.map((e) => e.uuid)).toEqual(['c', 'a'])
    })

    it('returns the same array reference when the batch contains only duplicates', () => {
        const state = [makeEvent('a')]
        expect(deduplicateEvents(state, [makeEvent('a')], 10)).toBe(state)
    })
})
