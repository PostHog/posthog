import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { buildSearchClause, hogInvocationsLogic, parentClauseFor } from './hogInvocationsLogic'

describe('hogInvocationsLogic', () => {
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

    describe('parentClauseFor', () => {
        const base = { id: 'flow-1', functionKind: 'hog_flow' as const }

        it('returns an empty clause when no parent run is scoped', () => {
            // Unscoped is the flat list. A non-empty clause here would wrongly filter the whole workflow's runs.
            expect(parentClauseFor(base).raw).toBe('')
        })

        it('scopes to the batch job id when parentRunId is set', () => {
            // The batch view depends on this: without it a job's table shows every run for the workflow,
            // not just that broadcast's. The id goes in as an escaped HogQL string literal.
            expect(parentClauseFor({ ...base, parentRunId: 'job-1' }).raw).toBe("AND parent_run_id = 'job-1'")
        })
    })

    describe('parent-run scope isolation', () => {
        beforeEach(() => {
            useMocks({
                post: {
                    '/api/environments/:team_id/query/': () => [200, { results: [] }],
                },
            })
            initKeaTests()
        })

        it('does not write a scoped table filters to the shared URL', async () => {
            // Several per-job tables can mount on one scene; if a scoped one wrote inv_* params it would
            // clobber the flat list and its siblings. The parentRunId guard in actionToUrl prevents that.
            const scoped = hogInvocationsLogic({ id: 'flow-1', functionKind: 'hog_flow', parentRunId: 'job-1' })
            scoped.mount()
            const before = { ...router.values.searchParams }
            await expectLogic(scoped, () => {
                scoped.actions.setFilters({ date_from: '-7d' })
            }).toDispatchActions(['setFilters'])
            expect(router.values.searchParams).toEqual(before)
            scoped.unmount()
        })

        it('the flat list still writes its filters to the URL', async () => {
            const flat = hogInvocationsLogic({ id: 'flow-1', functionKind: 'hog_flow' })
            flat.mount()
            await expectLogic(flat, () => {
                flat.actions.setFilters({ date_from: '-7d' })
            }).toDispatchActions(['setFilters'])
            expect(router.values.searchParams.inv_date_from).toBe('-7d')
            flat.unmount()
        })

        it('anchors the initial window to defaultDateFrom for a scoped table', () => {
            // A broadcast older than 24h would show no runs if the scoped table used the default -24h window.
            const scoped = hogInvocationsLogic({
                id: 'flow-1',
                functionKind: 'hog_flow',
                parentRunId: 'job-1',
                defaultDateFrom: '2026-01-01',
            })
            scoped.mount()
            expect(scoped.values.filters.date_from).toBe('2026-01-01')
            scoped.unmount()
        })
    })

    describe('best-effort person hydration', () => {
        beforeEach(() => {
            // The person-properties query fails; run loads succeed so mount isn't noisy.
            useMocks({
                post: {
                    // queryHogQL POSTs to /query/<kind>; fail only the person-properties query.
                    '/api/environments/:team_id/query/:kind': async ({ request }) => {
                        const body = (await request.json()) as Record<string, any>
                        if (String(body?.query?.query ?? '').includes('FROM persons')) {
                            return [500, { detail: 'boom' }]
                        }
                        return [200, { results: [] }]
                    },
                },
            })
            initKeaTests()
        })

        it('swallows a failed person-properties query instead of throwing', async () => {
            // A transient failure enriching the table with person props must not surface as an
            // error tracking issue: the loader falls back to the current map and the table just
            // renders without the extra props. Dropping the catch would dispatch a failure here.
            const logic = hogInvocationsLogic({ id: 'flow-1', functionKind: 'hog_flow' })
            logic.mount()
            await expectLogic(logic, () => {
                logic.actions.hydratePeople(['00000000-0000-0000-0000-000000000001'])
            })
                .toDispatchActions(['hydratePeople', 'hydratePeopleSuccess'])
                .toNotHaveDispatchedActions(['hydratePeopleFailure'])
            expect(logic.values.personPropertiesById).toEqual({})
            logic.unmount()
        })
    })
})
