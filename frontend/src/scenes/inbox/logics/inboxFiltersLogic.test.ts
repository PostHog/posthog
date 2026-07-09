import { buildSignalReportListOrdering } from './inboxFiltersLogic'

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
