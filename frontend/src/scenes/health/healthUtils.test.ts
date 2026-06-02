import { buildHealthIssuePrompt, buildHealthOverviewPrompt, HEALTH_OVERVIEW_QUESTIONS } from './healthUtils'
import type { HealthIssue } from './types'

const makeIssue = (overrides: Partial<HealthIssue> = {}): HealthIssue => ({
    id: 'issue-1',
    kind: 'ingestion_warning',
    severity: 'warning',
    status: 'active',
    dismissed: false,
    payload: {},
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    resolved_at: null,
    ...overrides,
})

describe('healthUtils prompt builders', () => {
    it('builds a single-issue prompt with label, severity, category and payload details', () => {
        const prompt = buildHealthIssuePrompt(
            makeIssue({
                kind: 'ingestion_warning',
                severity: 'critical',
                payload: { reason: 'Too many events', warning_type: 'cardinality', affected_count: 1234 },
            })
        )
        expect(prompt).toContain('Issue: Ingestion warning')
        expect(prompt).toContain('Severity: Critical')
        expect(prompt).toContain('Category: Ingestion')
        expect(prompt).toContain('Reason: Too many events')
        expect(prompt).toContain('Warning type: cardinality')
        expect(prompt).toContain('Affected count: 1234')
        expect(prompt).toContain('concrete steps to fix it')
    })

    it('omits the details section when the payload is empty', () => {
        const prompt = buildHealthIssuePrompt(makeIssue({ payload: {} }))
        expect(prompt).not.toContain('Details:')
    })

    it('flattens array payload values and truncates long strings', () => {
        const prompt = buildHealthIssuePrompt(
            makeIssue({
                kind: 'reverse_proxy',
                payload: { unproxied_hosts: ['a.com', 'b.com'], error: 'x'.repeat(1000) },
            })
        )
        expect(prompt).toContain('Unproxied hosts: a.com, b.com')
        expect(prompt).toContain('…')
        expect(prompt).not.toContain('x'.repeat(1000))
    })

    it('builds an overview prompt listing every issue sorted by severity', () => {
        const prompt = buildHealthOverviewPrompt([
            makeIssue({ id: '1', kind: 'sdk_outdated', severity: 'info' }),
            makeIssue({ id: '2', kind: 'ingestion_warning', severity: 'critical', payload: { reason: 'Spike' } }),
        ])
        expect(prompt).toContain('2 active health issues')
        expect(prompt).toContain('[Critical]')
        expect(prompt).toContain('[Info]')
        expect(prompt).toContain('Spike')
        // critical issues are listed before info ones
        expect(prompt.indexOf('Ingestion warning')).toBeLessThan(prompt.indexOf('SDK outdated'))
    })

    it('uses the singular form for a single issue', () => {
        const prompt = buildHealthOverviewPrompt([makeIssue()])
        expect(prompt).toContain('1 active health issue')
        expect(prompt).not.toContain('1 active health issues')
    })

    it('returns a monitoring prompt when there are no issues', () => {
        const prompt = buildHealthOverviewPrompt([])
        expect(prompt).toContain('no active health issues')
        expect(prompt).toContain('monitor')
    })

    it('starts the overview prompt with the chosen preset question', () => {
        const question = HEALTH_OVERVIEW_QUESTIONS[1]
        const prompt = buildHealthOverviewPrompt([makeIssue()], question)
        expect(prompt.startsWith(question)).toBe(true)
    })
})
