import {
    AnalyticsEvent,
    buildAnalyticsProperties,
    eventNameFor,
    PLATFORM_ORIGIN,
    PostHogLike,
    RoutingAnalyticsSink,
} from './analytics-sink'

interface CapturedCall {
    distinctId: string
    event: string
    properties?: Record<string, unknown>
    timestamp?: Date
}

/** Stub PostHog client — records captures, no network. One per api key. */
class FakeClient implements PostHogLike {
    captured: CapturedCall[] = []
    shutdownCount = 0
    capture(payload: CapturedCall): void {
        this.captured.push(payload)
    }
    async shutdown(): Promise<void> {
        this.shutdownCount++
    }
}

function genEvent(teamId: number, overrides: Partial<AnalyticsEvent> = {}): AnalyticsEvent {
    return {
        kind: 'generation',
        ts: '2026-06-10T00:00:00.000Z',
        team_id: teamId,
        application_id: 'app_1',
        revision_id: 'rev_1',
        session_id: 'sess_1',
        turn: 1,
        span_id: 'sess_1:gen:1',
        distinct_id: 'pat:user-1',
        model: 'anthropic/claude-haiku-4-5',
        provider: 'anthropic',
        input: [{ role: 'user', content: 'hi' }],
        output: [{ type: 'text', text: 'hello' }],
        input_tokens: 10,
        output_tokens: 5,
        latency_ms: 1200,
        cost: { source: 'gateway', usd: 0.002 },
        stop_reason: 'stop',
        ...overrides,
    } as AnalyticsEvent
}

/** Build a sink with stub clients keyed by api key. Returns the sink + the client registry. */
function buildSink(opts: {
    resolveApiKey: (teamId: number) => Promise<string | null>
    fallbackApiKey?: string
    maxClients?: number
}): { sink: RoutingAnalyticsSink; clients: Map<string, FakeClient>; warnings: string[] } {
    const clients = new Map<string, FakeClient>()
    const warnings: string[] = []
    const sink = new RoutingAnalyticsSink({
        resolveApiKey: opts.resolveApiKey,
        fallbackApiKey: opts.fallbackApiKey,
        maxClients: opts.maxClients,
        createClient: (apiKey) => {
            const c = new FakeClient()
            clients.set(apiKey, c)
            return c
        },
        logger: {
            info: () => undefined,
            warn: (m) => warnings.push(m),
            error: (m) => warnings.push(m),
        },
    })
    return { sink, clients, warnings }
}

describe('buildAnalyticsProperties', () => {
    it('stamps the platform origin + agent ids on every event', () => {
        const props = buildAnalyticsProperties(genEvent(7))
        expect(props.$ai_origin).toBe(PLATFORM_ORIGIN)
        expect(props.$ai_trace_id).toBe('sess_1')
        expect(props.$agent_application_id).toBe('app_1')
        expect(props.team_id).toBe(7)
    })

    it('maps a trace event to $ai_trace with name + input/output state', () => {
        const trace: AnalyticsEvent = {
            kind: 'trace',
            ts: '2026-06-10T00:00:00.000Z',
            team_id: 7,
            application_id: 'app_1',
            revision_id: 'rev_1',
            session_id: 'sess_1',
            turn: 3,
            span_id: 'sess_1',
            distinct_id: 'pat:user-1',
            trace_name: 'Kudos bot',
            input_state: [{ role: 'user', content: 'go' }],
            output_state: [{ type: 'text', text: 'done' }],
        }
        expect(eventNameFor(trace)).toBe('$ai_trace')
        const props = buildAnalyticsProperties(trace)
        expect(props.$ai_span_name).toBe('Kudos bot')
        expect(props.$ai_input_state).toEqual([{ role: 'user', content: 'go' }])
        expect(props.$ai_output_state).toEqual([{ type: 'text', text: 'done' }])
    })
})

describe('RoutingAnalyticsSink', () => {
    it('routes each team’s events to that team’s own project key', async () => {
        const { sink, clients } = buildSink({
            resolveApiKey: async (teamId) => `phc_team_${teamId}`,
        })
        await sink.write([genEvent(1), genEvent(2), genEvent(1, { span_id: 'sess_1:gen:2', turn: 2 })])

        expect([...clients.keys()].sort()).toEqual(['phc_team_1', 'phc_team_2'])
        expect(clients.get('phc_team_1')!.captured).toHaveLength(2)
        expect(clients.get('phc_team_2')!.captured).toHaveLength(1)
        expect(clients.get('phc_team_1')!.captured[0].event).toBe('$ai_generation')
    })

    it('falls back to the global key when a team has no project key', async () => {
        const { sink, clients } = buildSink({
            resolveApiKey: async () => null,
            fallbackApiKey: 'phc_fallback',
        })
        await sink.write([genEvent(99)])
        expect([...clients.keys()]).toEqual(['phc_fallback'])
        expect(clients.get('phc_fallback')!.captured).toHaveLength(1)
    })

    it('drops events (no throw) when there is no key and no fallback', async () => {
        const taps: Array<string | null> = []
        const clients = new Map<string, FakeClient>()
        const sink = new RoutingAnalyticsSink({
            resolveApiKey: async () => null,
            createClient: (apiKey) => {
                const c = new FakeClient()
                clients.set(apiKey, c)
                return c
            },
            tap: ({ apiKey }) => taps.push(apiKey),
            logger: { info: () => undefined, warn: () => undefined, error: () => undefined },
        })
        await expect(sink.write([genEvent(5)])).resolves.toBeUndefined()
        expect(clients.size).toBe(0)
        expect(taps).toEqual([null])
    })

    it('treats a resolver error as no-key (best-effort, never throws)', async () => {
        const { sink, clients, warnings } = buildSink({
            resolveApiKey: async () => {
                throw new Error('db down')
            },
            fallbackApiKey: 'phc_fallback',
        })
        await sink.write([genEvent(5)])
        expect(clients.get('phc_fallback')!.captured).toHaveLength(1)
        expect(warnings.some((w) => w.includes('resolve'))).toBe(true)
    })

    it('drains every client on shutdown', async () => {
        const { sink, clients } = buildSink({
            resolveApiKey: async (teamId) => `phc_team_${teamId}`,
        })
        await sink.write([genEvent(1), genEvent(2)])
        await sink.shutdown()
        expect(clients.get('phc_team_1')!.shutdownCount).toBe(1)
        expect(clients.get('phc_team_2')!.shutdownCount).toBe(1)
    })

    it('LRU-evicts + drains the oldest client past maxClients', async () => {
        const { sink, clients } = buildSink({
            resolveApiKey: async (teamId) => `phc_team_${teamId}`,
            maxClients: 2,
        })
        await sink.write([genEvent(1)])
        await sink.write([genEvent(2)])
        await sink.write([genEvent(3)]) // evicts team_1 (least-recently-used)
        // give the background eviction shutdown a tick to settle
        await Promise.resolve()
        expect(clients.get('phc_team_1')!.shutdownCount).toBe(1)
        expect(clients.get('phc_team_2')!.shutdownCount).toBe(0)
        expect(clients.get('phc_team_3')!.shutdownCount).toBe(0)
    })
})
