import {
    buildSignalReportListOrdering,
    filterSearchParams,
    InboxFilterState,
    parseFilterSearchParams,
} from './inboxFiltersLogic'

const DEFAULT_STATE: InboxFilterState = {
    scope: 'for-you',
    sourceProductFilter: [],
    priorityFilter: [],
    sortField: 'priority',
    sortDirection: 'asc',
    searchQuery: '',
}

describe('inboxFiltersLogic', () => {
    describe('buildSignalReportListOrdering', () => {
        it('leads with the selected time field so "Newest first" surfaces the newest reports', () => {
            // The list is flat, so created_at must be the primary key — not a sub-sort within status buckets.
            expect(buildSignalReportListOrdering('created_at', 'desc')).toBe('-created_at,status,-updated_at')
        })

        it('leads with created_at ascending for "Oldest first"', () => {
            expect(buildSignalReportListOrdering('created_at', 'asc')).toBe('created_at,status,-updated_at')
        })

        it('leads with updated_at and drops the redundant tiebreak for "Last updated first"', () => {
            expect(buildSignalReportListOrdering('updated_at', 'desc')).toBe('-updated_at,status')
        })

        it('leads with priority for "Priority first"', () => {
            expect(buildSignalReportListOrdering('priority', 'asc')).toBe('priority,status,-updated_at')
        })
    })

    describe('filter URL params', () => {
        // Keeps shared links clean: a default view must not carry any filter params.
        it('omits all default filters from the URL', () => {
            expect(filterSearchParams(DEFAULT_STATE)).toEqual({})
        })

        it.each<[string, InboxFilterState, Record<string, string>]>([
            [
                'scope + sources + priorities + custom sort + search',
                {
                    scope: 'entire-project',
                    sourceProductFilter: ['error_tracking', 'github'],
                    priorityFilter: ['P0', 'P2'],
                    sortField: 'created_at',
                    sortDirection: 'desc',
                    searchQuery: 'checkout crash',
                },
                {
                    scope: 'entire-project',
                    source: 'error_tracking,github',
                    priority: 'P0,P2',
                    sort: 'created_at:desc',
                    search: 'checkout crash',
                },
            ],
            [
                'teammate scope only',
                { ...DEFAULT_STATE, scope: 'teammate:0199ed4a-5c03-0000-3220-df21df612e95' },
                { scope: 'teammate:0199ed4a-5c03-0000-3220-df21df612e95' },
            ],
        ])('round-trips %s through encode/decode', (_name, state, expectedParams) => {
            expect(filterSearchParams(state)).toEqual(expectedParams)
            expect(parseFilterSearchParams(expectedParams)).toEqual(state)
        })

        // A shared link is authoritative but untrusted: unknown values (a malformed teammate id, which would
        // otherwise reach the report-list API as a bad reviewer UUID, and a syntactically valid but
        // unsupported sort combination the Sort control can't display) must not leak into filter state.
        it('drops unknown sources, priorities, malformed teammate scope and unsupported sort', () => {
            expect(
                parseFilterSearchParams({
                    scope: 'teammate:not-a-uuid',
                    source: 'error_tracking,bogus_source',
                    priority: 'P9,P1',
                    // priority:desc has a valid field and direction but is not one of the offered sort options.
                    sort: 'priority:desc',
                })
            ).toEqual({
                ...DEFAULT_STATE,
                sourceProductFilter: ['error_tracking'],
                priorityFilter: ['P1'],
            })
        })
    })
})
