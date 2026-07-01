import { type AnalyticsGenerationEvent, buildAnalyticsProperties } from './analytics-sink'
import { HttpGatewayClient } from './gateway-client'
import {
    assertGatewayProvenance,
    extractGatewayRequestId,
    GATEWAY_REQUEST_ID_HEADER,
    gatewayAuthHeader,
    gatewaySettledCost,
    gatewayUsagePath,
} from './gateway-wire'
import type { HttpFetcher } from './http-client'

// Minimal fetch stub: queue of {status, body} responses returned in
// order. The tests assert on the *request* via `calls` and on the *response*
// via the return value.
interface FakeResponse {
    status: number
    body: unknown
}

interface CapturedCall {
    url: string
    method: string
    authorization?: string
}

function installFetch(queue: FakeResponse[]): { http: HttpFetcher; calls: CapturedCall[]; restore: () => void } {
    const calls: CapturedCall[] = []
    const http: HttpFetcher = {
        fetch: async (input, init) => {
            const url = typeof input === 'string' ? input : input.toString()
            const headers = init?.headers as Record<string, string> | undefined
            calls.push({
                url,
                method: init?.method ?? 'GET',
                authorization: headers?.['Authorization'] ?? headers?.['authorization'],
            })
            const next = queue.shift()
            if (!next) {
                throw new Error('fake fetch: queue empty')
            }
            const body = typeof next.body === 'string' ? next.body : JSON.stringify(next.body)
            return new Response(body, { status: next.status, headers: { 'Content-Type': 'application/json' } })
        },
    }
    return { http, calls, restore: () => {} }
}

describe('HttpGatewayClient.getUsage', () => {
    it('returns the parsed body on 200', async () => {
        const { http, calls, restore } = installFetch([
            {
                status: 200,
                body: {
                    request_id: 'agent:s1:1',
                    team_id: 1,
                    cost_usd: '0.000043',
                    input_tokens: 13,
                    output_tokens: 1,
                    settled_at: '2026-05-29T17:08:15Z',
                },
            },
        ])
        try {
            const c = new HttpGatewayClient({ baseUrl: 'http://gw.local/v1', http })
            const usage = await c.getUsage('agent:s1:1', { phc: 'phc_abc' })
            expect(usage?.cost_usd).toBe('0.000043')
            expect(usage?.team_id).toBe(1)
            expect(calls).toHaveLength(1)
            expect(calls[0].url).toBe('http://gw.local/v1/usage/agent:s1:1')
            expect(calls[0].authorization).toBe('Bearer phc_abc')
        } finally {
            restore()
        }
    })

    it('does NOT URL-encode the request_id (path-param routers reject %3A)', async () => {
        // Regression for the chi/Go encoding bug: encoded colons return 404
        // on the gateway side because chi.URLParam returns the raw escaped
        // segment.
        const { http, calls, restore } = installFetch([
            { status: 200, body: { request_id: 'x', team_id: 0, cost_usd: '0', settled_at: '' } },
        ])
        try {
            const c = new HttpGatewayClient({ baseUrl: 'http://gw/v1', http })
            await c.getUsage('agent:s1:1', { phc: 'phc_x' })
            expect(calls[0].url).toContain(':') // literal colons in the URL
            expect(calls[0].url).not.toContain('%3A')
        } finally {
            restore()
        }
    })

    it('retries on 404 with backoff and eventually returns the body', async () => {
        const { http, calls, restore } = installFetch([
            { status: 404, body: { error: 'not found' } },
            { status: 404, body: { error: 'not found' } },
            { status: 200, body: { request_id: 'x', team_id: 0, cost_usd: '0.001', settled_at: '' } },
        ])
        try {
            const c = new HttpGatewayClient({
                baseUrl: 'http://gw/v1',
                maxAttempts: 4,
                initialBackoffMs: 1,
                http,
            })
            const usage = await c.getUsage('x', { phc: 'phc' })
            expect(usage?.cost_usd).toBe('0.001')
            expect(calls).toHaveLength(3)
        } finally {
            restore()
        }
    })

    it('returns null after max 404 attempts without throwing', async () => {
        const { http, calls, restore } = installFetch([
            { status: 404, body: '' },
            { status: 404, body: '' },
        ])
        try {
            const c = new HttpGatewayClient({
                baseUrl: 'http://gw/v1',
                maxAttempts: 2,
                initialBackoffMs: 1,
                http,
            })
            const usage = await c.getUsage('x', { phc: 'phc' })
            expect(usage).toBeNull()
            expect(calls).toHaveLength(2)
        } finally {
            restore()
        }
    })

    it('returns null on non-404 errors without throwing', async () => {
        const { http, restore } = installFetch([{ status: 500, body: { error: 'boom' } }])
        try {
            const c = new HttpGatewayClient({ baseUrl: 'http://gw/v1', maxAttempts: 1, http })
            const usage = await c.getUsage('x', { phc: 'phc' })
            expect(usage).toBeNull()
        } finally {
            restore()
        }
    })
})

describe('HttpGatewayClient.getWalletBalance', () => {
    it('returns the parsed body on 200', async () => {
        const { http, calls, restore } = installFetch([
            {
                status: 200,
                body: {
                    team_id: 1,
                    available_usd: '99.999957',
                    pending_usd: '0',
                    currency: 'USD',
                },
            },
        ])
        try {
            const c = new HttpGatewayClient({ baseUrl: 'http://gw/v1', http })
            const bal = await c.getWalletBalance({ phc: 'phc_z' })
            expect(bal.available_usd).toBe('99.999957')
            expect(bal.currency).toBe('USD')
            expect(calls[0].url).toBe('http://gw/v1/wallet/balance')
            expect(calls[0].authorization).toBe('Bearer phc_z')
        } finally {
            restore()
        }
    })

    it('throws on non-200', async () => {
        const { http, restore } = installFetch([{ status: 503, body: { error: 'down' } }])
        try {
            const c = new HttpGatewayClient({ baseUrl: 'http://gw/v1', http })
            await expect(c.getWalletBalance({ phc: 'phc' })).rejects.toThrow(/wallet balance fetch failed/)
        } finally {
            restore()
        }
    })
})

describe('gateway-wire: request id single-sourcing (dispatch -> settled-cost lookup)', () => {
    it.each([
        { minted: 'gw-req-a1b2c3', clientChosen: 'agent:sess-1:1:11111111-1111-1111-1111-111111111111' },
        { minted: 'gw-req-z9y8x7', clientChosen: 'agent:sess-2:4:22222222-2222-2222-2222-222222222222' },
    ])(
        'keys the settled-cost lookup on the gateway-minted id ($minted), never the dispatch-side id ($clientChosen)',
        async ({ minted, clientChosen }) => {
            // The gateway ignores the client-sent id (e.g. Idempotency-Key) and
            // returns its own settlement id in a response header.
            const dispatchResponseHeaders: Record<string, string | undefined> = {
                [GATEWAY_REQUEST_ID_HEADER]: minted,
                'idempotency-key': clientChosen,
            }
            const extractedId = extractGatewayRequestId(dispatchResponseHeaders)
            expect(extractedId).toBe(minted)

            const { http, calls, restore } = installFetch([
                { status: 200, body: { request_id: minted, team_id: 1, cost_usd: '0.01', settled_at: '' } },
            ])
            try {
                const client = new HttpGatewayClient({ baseUrl: 'http://gw/v1', http })
                const usage = await client.getUsage(extractedId!, { phc: 'phc_test' })

                // Driven through the public `getUsage` API with the id
                // `extractGatewayRequestId` produced — the lookup URL is built
                // from that same id via `gatewayUsagePath`, never the
                // client-chosen one.
                expect(calls).toHaveLength(1)
                expect(calls[0].url).toBe(`http://gw/v1${gatewayUsagePath(minted)}`)
                expect(calls[0].url).not.toContain(clientChosen)
                expect(usage?.request_id).toBe(minted)
            } finally {
                restore()
            }
        }
    )

    it('extracts nothing when the gateway never stamped the header — never falls back to a client-chosen id', () => {
        expect(extractGatewayRequestId({})).toBeUndefined()
        expect(extractGatewayRequestId({ 'idempotency-key': 'agent:sess:1:nonce' })).toBeUndefined()
    })

    it.each(['phc_abc123', 'phs_project-secret'])(
        'getUsage authenticates with exactly what gatewayAuthHeader builds for %s',
        async (token) => {
            const { http, calls, restore } = installFetch([
                { status: 200, body: { request_id: 'x', team_id: 0, cost_usd: '0', settled_at: '' } },
            ])
            try {
                const client = new HttpGatewayClient({ baseUrl: 'http://gw/v1', http })
                await client.getUsage('x', { phc: token })
                expect(calls[0].authorization).toBe(gatewayAuthHeader(token).Authorization)
            } finally {
                restore()
            }
        }
    )
})

describe('gateway-wire: cost provenance guard', () => {
    it.each([
        ['0.42', 0.42],
        ['0', 0],
        ['1234.5678', 1234.5678],
    ])('gatewaySettledCost tags a finite wire value (%s) as gateway-settled', (wire, expected) => {
        expect(gatewaySettledCost({ cost_usd: wire })).toEqual({ source: 'gateway', usd: expected })
    })

    it.each(['not-a-number', 'NaN', 'Infinity'])(
        'gatewaySettledCost returns null for a non-finite wire value (%s)',
        (wire) => {
            expect(gatewaySettledCost({ cost_usd: wire })).toBeNull()
        }
    )

    it('accepts a genuinely gateway-settled cost', () => {
        expect(assertGatewayProvenance({ source: 'gateway', usd: 0.1 })).toEqual({ source: 'gateway', usd: 0.1 })
    })

    it.each([
        { source: 'pi_estimate', usd: 0.5 },
        { source: 'client_side', usd: 1 },
        { source: undefined, usd: 2 },
        { source: 'gateway', usd: Number.NaN },
        { source: 'gateway', usd: 'not-a-number' },
    ])('rejects a non-gateway-provenance cost (source=$source, usd=$usd)', ({ source, usd }) => {
        expect(() => assertGatewayProvenance({ source, usd })).toThrow(/non-gateway/)
    })

    it('the single analytics emission point (buildAnalyticsProperties) drops a forged non-gateway cost with an error, not silently', () => {
        const baseEvent: Omit<AnalyticsGenerationEvent, 'cost'> = {
            kind: 'generation',
            ts: '2026-06-10T00:00:00.000Z',
            team_id: 1,
            application_id: 'app_1',
            revision_id: 'rev_1',
            session_id: 'sess_1',
            turn: 1,
            span_id: 'sess_1:gen:1',
            distinct_id: 'agent:app_1',
            model: 'anthropic/claude-haiku-4-5',
            provider: 'anthropic',
            input: [],
            output: [],
            input_tokens: 1,
            output_tokens: 1,
            latency_ms: 10,
        }
        // A pi-ai estimate forged into the branded slot via a cast — the only way
        // this can resurface once the type blocks a plain literal. The runtime
        // guard must still catch it.
        const forged = { ...baseEvent, cost: { source: 'pi_estimate', usd: 99 } } as unknown as AnalyticsGenerationEvent
        expect(() => buildAnalyticsProperties(forged)).toThrow(/non-gateway/)

        const legitimate: AnalyticsGenerationEvent = { ...baseEvent, cost: { source: 'gateway', usd: 0.03 } }
        expect(buildAnalyticsProperties(legitimate).$ai_total_cost_usd).toBe(0.03)
    })
})
