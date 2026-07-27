/**
 * AI observability emission: the runner captures one `$ai_generation` per model
 * call, one `$ai_span` per tool dispatch, and one `$ai_trace` per session — and
 * routes every event to the OWNING TEAM's own project key (`team_id → phc_`), so
 * agent traffic shows up natively in that team's AI observability with zero config.
 *
 * The harness wires a real `RoutingAnalyticsSink` with a stub per-team resolver
 * (`team_id → phc_team_<id>`); `c.analytics` taps the wire shape it would POST.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

describe('ai observability: real e2e', () => {
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

    it('emits generation + span + trace, all routed to the team’s own project key', async () => {
        c.setScript([fauxCallTool('@posthog/query', { query: 'select 1' }), fauxText('done')])
        await c.deployAgent({
            slug: 'observed',
            name: 'Observed agent',
            spec: { tools: [{ kind: 'native', id: '@posthog/query' }] },
        })
        const res = await request(c.ingress).post('/agents/observed/run').send({ message: 'go' })
        await c.drain()
        const sessionId = res.body.session_id as string

        const events = c.analytics.forSession(sessionId)
        const names = events.map((e) => e.eventName)
        expect(names).toContain('$ai_generation')
        expect(names).toContain('$ai_span')
        expect(names).toContain('$ai_trace')

        // Every event for this session routes to the owning team's own key.
        const teamId = events[0].event.team_id
        expect(teamId).toBe(1)
        for (const e of events) {
            expect(e.apiKey).toBe(`phc_team_${teamId}`)
        }

        // Generation carries the trace + agent identifiers + platform origin.
        const gen = events.find((e) => e.eventName === '$ai_generation')!
        expect(gen.properties.$ai_trace_id).toBe(sessionId)
        expect(gen.properties.$agent_session_id).toBe(sessionId)
        expect(gen.properties.$agent_application_id).toBeTruthy()
        expect(gen.properties.$ai_origin).toBe('agent_platform_runner')
        expect(gen.properties.team_id).toBe(teamId)

        // Span names the tool and chains to its parent generation.
        const span = events.find((e) => e.eventName === '$ai_span')!
        expect(span.properties.$ai_span_name).toBe('@posthog/query')
        expect(span.properties.$ai_parent_id).toBeTruthy()

        // Exactly one trace, named after the agent, sharing the session trace id.
        const traces = events.filter((e) => e.eventName === '$ai_trace')
        expect(traces).toHaveLength(1)
        expect(traces[0].properties.$ai_span_name).toBe('Observed agent')
        expect(traces[0].properties.$ai_trace_id).toBe(sessionId)

        // The destination key is derived from the event's own team_id — the
        // routing-by-team mechanism (multiple keys, fallback, drop) is covered
        // exhaustively in agent-shared's analytics-sink unit tests.
        expect(gen.event.team_id).toBe(teamId)
    })
})
