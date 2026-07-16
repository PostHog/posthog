import { buildSearchClause } from './hogInvocationsLogic'

describe('buildSearchClause', () => {
    const props = { id: 'flow-1', functionKind: 'hog_flow' as const }

    it('returns an empty clause when no search is set', () => {
        // An empty clause when a search IS set (covered below) would silently show every run — the
        // failure mode worth locking.
        expect(buildSearchClause(props, { date_from: '-24h' }).raw).toBe('')
    })

    it('matches the typed term as an exact id OR a log-message substring', () => {
        // One typed term goes into every arm: it's compared for equality against each id column (paste
        // an id to find that run) and, via a log_entries subquery, as a substring of the message (type
        // words to find a run that logged them). So the same term appears in all arms below.
        const clause = buildSearchClause(props, { date_from: '-24h', search: 'run-42' }).raw
        expect(clause).toContain("invocation_id = 'run-42'")
        expect(clause).toContain("event_uuid = 'run-42'")
        expect(clause).toContain("distinct_id = 'run-42'")
        expect(clause).toContain("person_id = 'run-42'")
        expect(clause).toContain('FROM log_entries')
        expect(clause).toContain("message ILIKE concat('%', 'run-42', '%')")
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

    it('escapes ILIKE wildcards in the message arm but not the id arms', () => {
        // Typing "a%b" must match that literal text in messages, not "a<anything>b". The % is
        // backslash-escaped only for the ILIKE arm (then doubled by escapeHogQLString for the SQL
        // literal); the exact-id arms keep the raw term.
        const clause = buildSearchClause(props, { date_from: '-24h', search: 'a%b' }).raw
        expect(clause).toContain("invocation_id = 'a%b'")
        expect(clause).toContain("message ILIKE concat('%', 'a\\\\%b', '%')")
    })
})
