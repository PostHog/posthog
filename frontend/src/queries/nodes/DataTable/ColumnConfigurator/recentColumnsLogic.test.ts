import { initKeaTests } from '~/test/init'

import { MAX_RECENT_COLUMNS_PER_CONTEXT, RECENT_COLUMN_MAX_AGE_MS, recentColumnsLogic } from './recentColumnsLogic'

describe('recentColumnsLogic', () => {
    let logic: ReturnType<typeof recentColumnsLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = recentColumnsLogic.build()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('starts with empty recents', () => {
        expect(logic.values.recentColumnsByContext).toEqual({})
        expect(logic.values.recentColumnsForContext('live_events')).toEqual([])
    })

    it('records a column under the right context', () => {
        logic.actions.recordRecentColumn('live_events', 'properties.email')
        expect(logic.values.recentColumnsForContext('live_events')).toEqual(['properties.email'])
        expect(logic.values.recentColumnsForContext('groups:0')).toEqual([])
    })

    it('prepends most recent first and dedupes by exact column string', () => {
        logic.actions.recordRecentColumn('live_events', 'a')
        logic.actions.recordRecentColumn('live_events', 'b')
        logic.actions.recordRecentColumn('live_events', 'a')
        expect(logic.values.recentColumnsForContext('live_events')).toEqual(['a', 'b'])
    })

    it('preserves SQL expressions verbatim', () => {
        const sql = `formatDateTime(toTimeZone(timestamp, 'Europe/Berlin'), '%b %d, %H:%i:%s') as "Absolute Time"`
        logic.actions.recordRecentColumn('live_events', sql)
        expect(logic.values.recentColumnsForContext('live_events')).toEqual([sql])
    })

    it('caps the per-context list at the maximum size', () => {
        for (let i = 0; i < MAX_RECENT_COLUMNS_PER_CONTEXT + 5; i++) {
            logic.actions.recordRecentColumn('live_events', `col_${i}`)
        }
        const recents = logic.values.recentColumnsForContext('live_events')
        expect(recents).toHaveLength(MAX_RECENT_COLUMNS_PER_CONTEXT)
        expect(recents[0]).toBe(`col_${MAX_RECENT_COLUMNS_PER_CONTEXT + 4}`)
    })

    it('drops entries older than the max age', () => {
        jest.useFakeTimers()
        const expiredTime = 1_700_000_000_000
        jest.setSystemTime(expiredTime)
        logic.actions.recordRecentColumn('live_events', 'old')

        jest.setSystemTime(expiredTime + RECENT_COLUMN_MAX_AGE_MS + 1000)
        logic.actions.recordRecentColumn('live_events', 'fresh')

        expect(logic.values.recentColumnsForContext('live_events')).toEqual(['fresh'])
        jest.useRealTimers()
    })

    it('keeps recents per context independent', () => {
        logic.actions.recordRecentColumn('live_events', 'event_col')
        logic.actions.recordRecentColumn('groups:0', 'group_col')

        expect(logic.values.recentColumnsForContext('live_events')).toEqual(['event_col'])
        expect(logic.values.recentColumnsForContext('groups:0')).toEqual(['group_col'])
    })

    it('clears only the requested context', () => {
        logic.actions.recordRecentColumn('live_events', 'a')
        logic.actions.recordRecentColumn('groups:0', 'b')
        logic.actions.clearRecentColumns('live_events')

        expect(logic.values.recentColumnsForContext('live_events')).toEqual([])
        expect(logic.values.recentColumnsForContext('groups:0')).toEqual(['b'])
    })

    it('ignores empty contextKey or empty column', () => {
        logic.actions.recordRecentColumn('', 'something')
        logic.actions.recordRecentColumn('live_events', '')
        expect(logic.values.recentColumnsByContext).toEqual({})
    })
})
