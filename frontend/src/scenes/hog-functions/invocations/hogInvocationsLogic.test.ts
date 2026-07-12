import { searchClauseFor, type HogInvocationsFilters } from './hogInvocationsLogic'

const baseFilters = (search?: string): HogInvocationsFilters => ({ date_from: '-24h', search })

describe('hogInvocationsLogic', () => {
    it('returns an empty clause when there is no search term', () => {
        expect(searchClauseFor(baseFilters(undefined)).raw).toBe('')
        expect(searchClauseFor(baseFilters('   ')).raw).toBe('')
    })

    it('matches the id columns and skips the persons subquery for a non-email term', () => {
        const raw = searchClauseFor(baseFilters('abc-123')).raw
        expect(raw).toContain("invocation_id = 'abc-123'")
        expect(raw).toContain("event_uuid = 'abc-123'")
        expect(raw).toContain("distinct_id = 'abc-123'")
        expect(raw).toContain("person_id = 'abc-123'")
        expect(raw).not.toContain('FROM persons')
    })

    it('resolves an email term to person ids via a persons subquery', () => {
        const raw = searchClauseFor(baseFilters('suped.dmarc@tetral.org')).raw
        // Still matches the id columns as before...
        expect(raw).toContain("distinct_id = 'suped.dmarc@tetral.org'")
        // ...and additionally resolves the email against person properties.
        expect(raw).toContain(
            "person_id IN (SELECT toString(id) FROM persons WHERE properties.email = 'suped.dmarc@tetral.org')"
        )
    })

    it('escapes the search term to guard against injection', () => {
        const raw = searchClauseFor(baseFilters("x@y' OR 1=1 --")).raw
        expect(raw).toContain("properties.email = 'x@y\\' OR 1=1 --'")
    })
})
