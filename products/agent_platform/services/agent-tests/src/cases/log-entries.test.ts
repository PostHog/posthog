/**
 * LogSink: the runner writes structured log entries for every session
 * lifecycle event. Tests use the InMemoryLogSink on the harness's cluster.logs
 * to assert on captured rows.
 *
 * Old equivalent: ClickHouse `log_entries` assertions in v1's runtime.test.ts,
 * cancel.test.ts, failure.test.ts.
 */

import request from 'supertest'

import type { SessionEvent } from '@posthog/agent-shared'

import {
    buildCluster,
    closeSharedPool,
    Cluster,
    fakeAuthProvider,
    fauxCallTool,
    fauxErrorTurn,
    fauxText,
} from '../harness'

describe('log sink: real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster()
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('writes session_started + turn_started + completed entries for a happy path', async () => {
        c.setScript([fauxText('done')])
        const { application } = await c.deployAgent({ slug: 'logs-1' })
        const run = await request(c.ingress).post('/agents/logs-1/run').send({ message: 'hi' })
        await c.drain()

        const entries = c.logs.forSession(run.body.session_id)
        const events = entries.map((e) => e.event)
        expect(events).toContain('session_started')
        expect(events).toContain('turn_started')
        expect(events).toContain('completed')
        // Every entry carries team + application + session ids.
        for (const e of entries) {
            expect(e.team_id).toBe(1)
            expect(e.application_id).toBe(application.id)
            expect(e.session_id).toBe(run.body.session_id)
        }
    })

    it('logs tool_call + tool_result events when the model invokes a tool', async () => {
        // @posthog/query acts as the calling posthog user against an explicit
        // project_id, so the run must authenticate as a posthog principal and
        // pass a project_id — otherwise the tool errors and tool_result.ok
        // would be false.
        const PAT = 'phx_log_entries'
        await c.teardown()
        c = await buildCluster({ authProvider: fakeAuthProvider({ posthog: PAT }) })
        c.setScript([fauxCallTool('@posthog/query', { project_id: 1, query: 'select 1' }), fauxText('done')])
        await c.deployAgent({
            slug: 'logs-tool',
            spec: { tools: [{ kind: 'native', id: '@posthog/query' }], auth: { modes: [{ type: 'posthog' }] } },
        })
        const run = await request(c.ingress)
            .post('/agents/logs-tool/run')
            .set('authorization', `Bearer ${PAT}`)
            .send({ message: 'go' })
        await c.drain()

        const entries = c.logs.forSession(run.body.session_id)
        const toolCall = entries.find((e) => e.event === 'tool_call')
        const toolResult = entries.find((e) => e.event === 'tool_result')
        expect(toolCall?.data.name).toBe('@posthog/query')
        expect(toolResult?.data.ok).toBe(true)
    })

    it('writes a failed entry at error level on upstream model failure', async () => {
        c.setScript([fauxErrorTurn('rate_limit')])
        await c.deployAgent({ slug: 'logs-fail' })
        const run = await request(c.ingress).post('/agents/logs-fail/run').send({ message: 'x' })
        await c.drain()

        const failed = c.logs.forSession(run.body.session_id).find((e) => e.event === 'failed')
        expect(failed).not.toBeUndefined()
        expect(failed!.level).toBe('error')
        expect(failed!.data.reason).toBe('rate_limit')
    })

    it('`failed` bus payload is empty — raw reason lives ONLY in log_entries', async () => {
        // The bus event is fanned out to every chat client connected to
        // the session. Raw failure reasons can carry provider error
        // bodies, internal URLs, model/provider ids — none of which
        // should be exposed to end users of someone-else's agent.
        // log_entries (which the session-detail page reads) is the
        // authoritative place for agent owners to see why a session
        // failed. This pins both halves of that contract.
        c.setScript([fauxErrorTurn('rate_limit')])
        await c.deployAgent({ slug: 'logs-fail-split' })

        const events: SessionEvent[] = []
        const run = await request(c.ingress).post('/agents/logs-fail-split/run').send({ message: 'x' })
        const sid = run.body.session_id
        const unsubscribe = c.bus.subscribe(sid, (e) => events.push(e))
        await c.drain()
        unsubscribe()

        const failedBus = events.find((e) => e.kind === 'failed')
        expect(failedBus).not.toBeUndefined()
        // No reason / source / model / provider on the bus — payload
        // is empty by design.
        expect(failedBus!.data).toEqual({})

        // But the log entry still carries everything an agent owner
        // needs to debug.
        const failedLog = c.logs.forSession(sid).find((e) => e.event === 'failed')
        expect(failedLog).not.toBeUndefined()
        expect(failedLog!.data.reason).toBe('rate_limit')
    })

    it('writes a completed entry when a text-only turn ends', async () => {
        // Asking the user a question is no longer a separate event — the
        // agent emits text and the turn ends normally with `completed`.
        c.setScript([fauxText('continue?')])
        await c.deployAgent({ slug: 'logs-wait' })
        const run = await request(c.ingress).post('/agents/logs-wait/run').send({ message: 'hi' })
        await c.drain()

        const entries = c.logs.forSession(run.body.session_id)
        const completed = entries.find((e) => e.event === 'completed')
        expect(completed).not.toBeUndefined()
    })
})
