import { buildSearchClause } from './hogInvocationsLogic'

describe('buildSearchClause', () => {
    const props = { id: 'flow-1', functionKind: 'hog_flow' as const }

    it('returns an empty clause when no search is set', () => {
        // An empty clause when a search IS set (covered below) would silently show every run — the
        // failure mode worth locking.
        expect(buildSearchClause(props, { date_from: '-24h' }).raw).toBe('')
    })

    it('matches an exact id OR a log-message substring', () => {
        const clause = buildSearchClause(props, { date_from: '-24h', search: 'bounce' }).raw
        // Exact-id arms — pasting a UUID still finds that one run.
        expect(clause).toContain("invocation_id = 'bounce'")
        expect(clause).toContain("event_uuid = 'bounce'")
        expect(clause).toContain("distinct_id = 'bounce'")
        expect(clause).toContain("person_id = 'bounce'")
        // ...OR a run that logged a matching message — the old Logs-tab behavior, folded in.
        expect(clause).toContain('FROM log_entries')
        expect(clause).toContain("message ILIKE concat('%', 'bounce', '%')")
        // No level narrowing for a manual search — it matches any level.
        expect(clause).not.toContain('lower(level)')
    })

    it('narrows the message match to log_levels when a drill-down sets them', () => {
        // Drill-downs carry levels so "Bounced" (WARN/ERROR) does not also match the INFO
        // "Email sent to bounce@…" log.
        const clause = buildSearchClause(props, {
            date_from: '-24h',
            search: 'bounce',
            log_levels: ['WARN', 'ERROR'],
        }).raw
        expect(clause).toContain("message ILIKE concat('%', 'bounce', '%')")
        expect(clause).toContain("lower(level) IN ('warn','error')")
    })
})
