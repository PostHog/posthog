import { logMessageClauseFor } from './hogInvocationsLogic'

describe('logMessageClauseFor', () => {
    const props = { id: 'flow-1', functionKind: 'hog_flow' as const }

    it('returns an empty clause when no log search is set', () => {
        // A non-empty clause here would be harmless, but an empty clause when a search IS set (the
        // inverse regression, covered below) would silently show every run — the failure mode worth locking.
        expect(logMessageClauseFor(props, { date_from: '-24h' }).raw).toBe('')
    })

    it('filters log_entries by message and level when set', () => {
        const clause = logMessageClauseFor(props, {
            date_from: '-24h',
            log_search: 'bounce',
            log_levels: ['WARN', 'ERROR'],
        }).raw
        expect(clause).toContain('FROM log_entries')
        expect(clause).toContain("message ILIKE concat('%', 'bounce', '%')")
        expect(clause).toContain("lower(level) IN ('warn','error')")
    })

    it('omits the level filter when no levels are given', () => {
        const clause = logMessageClauseFor(props, { date_from: '-24h', log_search: 'bounce' }).raw
        expect(clause).toContain("message ILIKE concat('%', 'bounce', '%')")
        expect(clause).not.toContain('lower(level)')
    })
})
