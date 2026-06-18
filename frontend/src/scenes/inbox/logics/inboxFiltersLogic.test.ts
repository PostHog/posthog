import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { buildSignalReportListOrdering, inboxFiltersLogic } from './inboxFiltersLogic'

// Mirrors kea-localstorage's key format: dotted logic path + reducer key.
const SORT_FIELD_KEY = 'scenes.inbox.logics.inboxFiltersLogic.sortField'
const SORT_DIRECTION_KEY = 'scenes.inbox.logics.inboxFiltersLogic.sortDirection'

describe('inboxFiltersLogic', () => {
    let logic: ReturnType<typeof inboxFiltersLogic.build>

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
    })

    afterEach(() => {
        logic?.unmount()
        localStorage.clear()
    })

    it('keeps a valid persisted sortField/sortDirection', async () => {
        localStorage.setItem(SORT_FIELD_KEY, JSON.stringify('updated_at'))
        localStorage.setItem(SORT_DIRECTION_KEY, JSON.stringify('desc'))

        logic = inboxFiltersLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ sortField: 'updated_at', sortDirection: 'desc' })
    })

    it('resets a stale persisted sortField to the default on mount', async () => {
        // A value persisted by an older client that's no longer a supported sort field.
        localStorage.setItem(SORT_FIELD_KEY, JSON.stringify('signal_count'))

        logic = inboxFiltersLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ sortField: 'priority', sortDirection: 'asc' })
    })

    it('resets a stale persisted sortDirection while keeping a valid sortField', async () => {
        localStorage.setItem(SORT_FIELD_KEY, JSON.stringify('created_at'))
        localStorage.setItem(SORT_DIRECTION_KEY, JSON.stringify('sideways'))

        logic = inboxFiltersLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ sortField: 'created_at', sortDirection: 'asc' })
    })

    describe('buildSignalReportListOrdering', () => {
        it('only ever emits clauses the backend recognises', () => {
            expect(buildSignalReportListOrdering('priority', 'asc')).toBe('status,priority,-updated_at')
            expect(buildSignalReportListOrdering('created_at', 'desc')).toBe('status,-created_at,-updated_at')
            // `updated_at` is its own recency tiebreak, so it isn't duplicated.
            expect(buildSignalReportListOrdering('updated_at', 'desc')).toBe('status,-updated_at')
        })
    })
})
