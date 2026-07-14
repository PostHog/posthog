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
                'scope + multiple sources + priorities + custom sort',
                {
                    scope: 'entire-project',
                    sourceProductFilter: ['error_tracking', 'github'],
                    priorityFilter: ['P0', 'P2'],
                    sortField: 'created_at',
                    sortDirection: 'desc',
                },
                { scope: 'entire-project', source: 'error_tracking,github', priority: 'P0,P2', sort: 'created_at:desc' },
            ],
            [
                'teammate scope only',
                { ...DEFAULT_STATE, scope: 'teammate:abc-123' },
                { scope: 'teammate:abc-123' },
            ],
        ])('round-trips %s through encode/decode', (_name, state, expectedParams) => {
            expect(filterSearchParams(state)).toEqual(expectedParams)
            expect(parseFilterSearchParams(expectedParams)).toEqual(state)
        })

        // A shared link is authoritative but untrusted: unknown values must not leak into the filter state.
        it('drops unknown sources, priorities, scope and sort, falling back to defaults', () => {
            expect(
                parseFilterSearchParams({
                    scope: 'nonsense',
                    source: 'error_tracking,bogus_source',
                    priority: 'P9,P1',
                    sort: 'foo:sideways',
                })
            ).toEqual({
                ...DEFAULT_STATE,
                sourceProductFilter: ['error_tracking'],
                priorityFilter: ['P1'],
            })
        })
    })
})
