/**
 * Unit tests for `loop/mcp-clients.ts`. Uses the SDK's `InMemoryTransport`
 * paired with a real `McpServer` so the round-trip exercises the actual
 * protocol — same pattern as `services/mcp/tests/unit/exec-description-emission.test.ts`.
 *
 * The factory injection point (`transportFactory`) is the only thing the
 * tests need to substitute; the rest of the module's behaviour
 * (auth-header stamping, secret substitution, partial-open cleanup) gets
 * exercised through the real `Client` over the in-memory pipe.
 */

import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js'
import { z } from 'zod'

import type { McpRef } from '@posthog/agent-shared'

import { McpTransportFactory, openMcpClients } from './mcp-clients'

type ToolCapturedCall = { name: string; args: Record<string, unknown>; headers: Record<string, string> | null }

/**
 * Spin up a tiny `McpServer` exposing `echo` + `boom` tools, return a transport
 * factory that pairs every connect with a fresh server instance. Captured
 * tool calls land in the returned array so tests can assert what the remote
 * actually saw.
 *
 * `pairs` is the inflight server handles keyed by the prefix the test gives
 * the factory — tests use it to close servers in their own `afterEach`.
 */
interface PairHandle {
    close: () => Promise<void>
    /**
     * Flips to true the first time the SDK calls `close()` on the
     * server-side transport — i.e. when the *runner* closed the
     * matching client. Used to verify the partial-open cleanup path
     * actually drains successful clients rather than leaking them.
     */
    serverClosed: { value: boolean }
}

async function buildEchoFactory(): Promise<{
    factory: McpTransportFactory
    calls: ToolCapturedCall[]
    pairs: PairHandle[]
    /**
     * Tracks the `{ url, headers }` payloads the factory was invoked with —
     * lets tests assert auth/secret substitution without parsing HTTP traffic.
     */
    targets: Array<{ url: string; headers: Record<string, string> }>
}> {
    const calls: ToolCapturedCall[] = []
    const pairs: PairHandle[] = []
    const targets: Array<{ url: string; headers: Record<string, string> }> = []
    const factory: McpTransportFactory = (target): Transport => {
        targets.push(target)
        const server = new McpServer({ name: 'echo-mcp', version: '1.0.0' })
        server.registerTool(
            'echo',
            {
                title: 'Echo',
                description: 'Echo the input back as text.',
                inputSchema: { msg: z.string() },
            },
            async ({ msg }) => {
                calls.push({ name: 'echo', args: { msg }, headers: null })
                return { content: [{ type: 'text' as const, text: msg }] }
            }
        )
        server.registerTool(
            'boom',
            {
                title: 'Boom',
                description: 'Always throws — used to exercise the error path.',
                inputSchema: {},
            },
            async () => {
                calls.push({ name: 'boom', args: {}, headers: null })
                throw new Error('boom_intentional')
            }
        )
        const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
        // Connect the server side eagerly — the SDK's `connect()` is fire-and-
        // forget at this layer; the linked pair carries the handshake.
        void server.server.connect(serverTransport)
        const serverClosed = { value: false }
        const originalServerClose = serverTransport.close?.bind(serverTransport)
        serverTransport.close = async () => {
            serverClosed.value = true
            await originalServerClose?.()
        }
        pairs.push({
            close: async () => {
                await clientTransport.close?.()
                await serverTransport.close?.()
            },
            serverClosed,
        })
        return clientTransport
    }
    return { factory, calls, pairs, targets }
}

async function closePairs(pairs: { close: () => Promise<void> }[]): Promise<void> {
    await Promise.all(pairs.map((p) => p.close()))
}

describe('openMcpClients', () => {
    it('returns an empty result for an empty refs list', async () => {
        const { factory, pairs, targets } = await buildEchoFactory()
        const { clients, close } = await openMcpClients([], {
            integrations: {},
            secrets: {},
            transportFactory: factory,
        })
        expect(clients).toEqual([])
        expect(targets).toEqual([]) // factory never invoked
        await close()
        await closePairs(pairs)
    })

    it('opens an external ref and lists+calls remote tools', async () => {
        const { factory, calls, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [{ id: 'echo', url: 'https://example.com/mcp', secrets: [] }]

        const { clients, close } = await openMcpClients(refs, {
            integrations: {},
            secrets: {},
            transportFactory: factory,
        })

        expect(clients).toHaveLength(1)
        expect(clients[0].prefix).toBe('echo')
        expect(clients[0].ref).toEqual(refs[0])

        const listed = await clients[0].listTools()
        const names = listed.map((t) => t.name).sort()
        expect(names).toEqual(['boom', 'echo'])
        expect(listed.find((t) => t.name === 'echo')?.description).toBe('Echo the input back as text.')

        const result = await clients[0].callTool('echo', { msg: 'hello' })
        expect(calls).toEqual([{ name: 'echo', args: { msg: 'hello' }, headers: null }])
        const text = (result.content as Array<{ type: string; text?: string }>)[0]
        expect(text.type).toBe('text')
        expect(text.text).toBe('hello')

        await close()
        await closePairs(pairs)
    })

    it('preserves the prefix as the entry id for external refs', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            { id: 'linear', url: 'https://example.com/linear', secrets: [] },
            { id: 'github', url: 'https://example.com/github', secrets: [] },
        ]
        const { clients, close } = await openMcpClients(refs, {
            integrations: {},
            secrets: {},
            transportFactory: factory,
        })
        expect(clients.map((c) => c.prefix).sort()).toEqual(['github', 'linear'])
        await close()
        await closePairs(pairs)
    })

    it('rejects duplicate prefixes across refs', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            { id: 'dup', url: 'https://example.com/a', secrets: [] },
            { id: 'dup', url: 'https://example.com/b', secrets: [] },
        ]
        await expect(
            openMcpClients(refs, { integrations: {}, secrets: {}, transportFactory: factory })
        ).rejects.toThrow(/duplicate_mcp_prefix: dup/)
        // The duplicate-prefix path closes the clients it opened — the in-memory
        // server pairs should still be drain-able by the test's own cleanup.
        await closePairs(pairs)
    })

    it('substitutes ${NAME} placeholders in url from secrets', async () => {
        const { factory, pairs, targets } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'tenant',
                url: 'https://example.com/${TENANT}/mcp',
                secrets: ['TENANT'],
            },
        ]
        const { close } = await openMcpClients(refs, {
            integrations: {},
            secrets: { TENANT: 'acme' },
            secretAllowedHosts: (n) => (n === 'TENANT' ? ['example.com'] : undefined),
            transportFactory: factory,
        })
        expect(targets).toHaveLength(1)
        expect(targets[0].url).toBe('https://example.com/acme/mcp')
        await close()
        await closePairs(pairs)
    })

    it('substitutes ${NAME} placeholders in author-supplied headers (BYO bearer token)', async () => {
        // The bring-your-own-token path: author pastes a PAT into spec.secrets,
        // references it via `Authorization: Bearer ${TOKEN}` on the MCP ref.
        // Plaintext substitution happens server-side so the token never appears
        // in the model's tool-call history. Same shape as @posthog/http-request.
        const { factory, pairs, targets } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'github',
                url: 'https://api.githubcopilot.com/mcp',
                secrets: ['GITHUB_TOKEN'],
                headers: {
                    Authorization: 'Bearer ${GITHUB_TOKEN}',
                    'X-GitHub-Api-Version': '2022-11-28',
                },
            },
        ]
        const { close } = await openMcpClients(refs, {
            integrations: {},
            secrets: { GITHUB_TOKEN: 'ghp_realtoken' },
            secretAllowedHosts: (n) => (n === 'GITHUB_TOKEN' ? ['api.githubcopilot.com'] : undefined),
            transportFactory: factory,
        })
        expect(targets[0].headers.Authorization).toBe('Bearer ghp_realtoken')
        expect(targets[0].headers['X-GitHub-Api-Version']).toBe('2022-11-28')
        await close()
        await closePairs(pairs)
    })

    it('author headers take precedence over integration-stamped Authorization on duplicate keys', async () => {
        // Matches @posthog/http-request's "caller-set values are not silently
        // overwritten" rule. If the author explicitly sets Authorization in
        // headers AND wires auth.integration, the explicit author value wins
        // — the integration bearer falls through. Authors who want the
        // integration's token must omit Authorization from headers.
        const { factory, pairs, targets } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'fancy',
                url: 'https://example.com/mcp',
                secrets: ['CUSTOM_TOKEN'],
                auth: { integration: 'slack:T01' },
                headers: { Authorization: 'Bearer ${CUSTOM_TOKEN}' },
            },
        ]
        const { close } = await openMcpClients(refs, {
            integrations: {
                'slack:T01': { kind: 'slack', access_token: 'xoxb-from-integration' },
            },
            secrets: { CUSTOM_TOKEN: 'custom-from-secret' },
            secretAllowedHosts: (n) => (n === 'CUSTOM_TOKEN' ? ['example.com'] : undefined),
            transportFactory: factory,
            integrationHostValidator: () => true,
        })
        expect(targets[0].headers.Authorization).toBe('Bearer custom-from-secret')
        await close()
        await closePairs(pairs)
    })

    it('reports a header-secret-missing ref as an unavailable MCP (auth category)', async () => {
        // Sending a literal `${NAME}` to the remote would 401 with a confusing
        // protocol error. We capture the resolver failure per-ref instead so
        // the session continues with the other MCPs and the agent's system
        // prompt mentions this one as unavailable.
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'github',
                url: 'https://example.com/mcp',
                secrets: ['GITHUB_TOKEN'],
                headers: { Authorization: 'Bearer ${GITHUB_TOKEN}' },
            },
        ]
        const { clients, close, failures } = await openMcpClients(refs, {
            integrations: {},
            secrets: {},
            transportFactory: factory,
        })
        expect(clients).toEqual([])
        expect(failures).toHaveLength(1)
        expect(failures[0].ref.id).toBe('github')
        expect(failures[0].category).toBe('auth')
        expect(failures[0].devReason).toMatch(/mcp_secret_not_resolved: GITHUB_TOKEN/)
        await close()
        await closePairs(pairs)
    })

    it('reports a url-secret-missing ref as an unavailable MCP (auth category)', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'tenant',
                url: 'https://example.com/${TENANT}/mcp',
                secrets: ['TENANT'],
            },
        ]
        const { clients, close, failures } = await openMcpClients(refs, {
            integrations: {},
            secrets: {},
            transportFactory: factory,
        })
        expect(clients).toEqual([])
        expect(failures).toHaveLength(1)
        expect(failures[0].ref.id).toBe('tenant')
        expect(failures[0].category).toBe('auth')
        expect(failures[0].devReason).toMatch(/mcp_secret_not_resolved: TENANT/)
        await close()
        await closePairs(pairs)
    })

    it('SECURITY: refuses to substitute a header secret pointed at a non-allowlisted host (exfil guard)', async () => {
        // The core threat: an author sets `Authorization: Bearer ${SLACK_BOT_TOKEN}`
        // but points `url` at a host they control. The secret is bound to
        // slack.com via spec.secrets[].allowed_hosts, so substitution must be
        // refused before the token is stamped onto a request to the attacker host.
        const { factory, pairs, targets } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'exfil',
                url: 'https://attacker.example.com/collect',
                secrets: ['SLACK_BOT_TOKEN'],
                headers: { Authorization: 'Bearer ${SLACK_BOT_TOKEN}' },
            },
        ]
        const { clients, close, failures } = await openMcpClients(refs, {
            integrations: {},
            secrets: { SLACK_BOT_TOKEN: 'xoxb-secret' },
            secretAllowedHosts: (n) => (n === 'SLACK_BOT_TOKEN' ? ['slack.com'] : undefined),
            transportFactory: factory,
        })
        expect(clients).toEqual([])
        expect(failures[0].category).toBe('auth')
        expect(failures[0].devReason).toMatch(/mcp_secret_host_not_allowed: SLACK_BOT_TOKEN -> attacker\.example\.com/)
        // The factory must never have been invoked — the token never reached a transport.
        expect(targets).toEqual([])
        await close()
        await closePairs(pairs)
    })

    it('SECURITY: refuses to substitute a bare-string (unbound) header secret (fail closed)', async () => {
        // A secret declared in spec.secrets[] as a bare string carries no
        // network-egress authority — same fail-closed shape as the unwired
        // integration-host-validator branch.
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'github',
                url: 'https://api.githubcopilot.com/mcp',
                secrets: ['GITHUB_TOKEN'],
                headers: { Authorization: 'Bearer ${GITHUB_TOKEN}' },
            },
        ]
        const { clients, close, failures } = await openMcpClients(refs, {
            integrations: {},
            secrets: { GITHUB_TOKEN: 'ghp_realtoken' },
            // null = declared as a bare string in spec.secrets[].
            secretAllowedHosts: (n) => (n === 'GITHUB_TOKEN' ? null : undefined),
            transportFactory: factory,
        })
        expect(clients).toEqual([])
        expect(failures[0].category).toBe('auth')
        expect(failures[0].devReason).toMatch(/mcp_secret_no_host_binding: GITHUB_TOKEN/)
        await close()
        await closePairs(pairs)
    })

    it('SECURITY: fails closed when secretAllowedHosts is not wired but a secret is referenced', async () => {
        // A deploy that forgets to wire the host lookup must not silently
        // regress to "send the secret to any host." Unset lookup → every
        // referenced secret is treated as unbound.
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'github',
                url: 'https://api.githubcopilot.com/mcp',
                secrets: ['GITHUB_TOKEN'],
                headers: { Authorization: 'Bearer ${GITHUB_TOKEN}' },
            },
        ]
        const { clients, close, failures } = await openMcpClients(refs, {
            integrations: {},
            secrets: { GITHUB_TOKEN: 'ghp_realtoken' },
            transportFactory: factory,
        })
        expect(clients).toEqual([])
        expect(failures[0].category).toBe('auth')
        expect(failures[0].devReason).toMatch(/mcp_secret_no_host_binding: GITHUB_TOKEN/)
        await close()
        await closePairs(pairs)
    })

    it('SECURITY: refuses to substitute a url secret pointed at a non-allowlisted host', async () => {
        // The URL itself can exfiltrate a secret (query string, path) to an
        // attacker host. The final-host check applies to URL substitution too.
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'tenant',
                url: 'https://attacker.example.com/${TENANT}/mcp',
                secrets: ['TENANT'],
            },
        ]
        const { clients, close, failures } = await openMcpClients(refs, {
            integrations: {},
            secrets: { TENANT: 'super-secret-tenant' },
            secretAllowedHosts: (n) => (n === 'TENANT' ? ['example.com'] : undefined),
            transportFactory: factory,
        })
        expect(clients).toEqual([])
        expect(failures[0].category).toBe('auth')
        expect(failures[0].devReason).toMatch(/mcp_secret_host_not_allowed: TENANT -> attacker\.example\.com/)
        await close()
        await closePairs(pairs)
    })

    it('substitutes a header secret when the final URL host is in its allowlist (wildcard)', async () => {
        // The allow path: a secret bound to `*.example.com` substitutes into a
        // request to a matching subdomain.
        const { factory, pairs, targets } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'svc',
                url: 'https://api.example.com/mcp',
                secrets: ['SVC_TOKEN'],
                headers: { Authorization: 'Bearer ${SVC_TOKEN}' },
            },
        ]
        const { close } = await openMcpClients(refs, {
            integrations: {},
            secrets: { SVC_TOKEN: 'tok_ok' },
            secretAllowedHosts: (n) => (n === 'SVC_TOKEN' ? ['*.example.com'] : undefined),
            transportFactory: factory,
        })
        expect(targets[0].headers.Authorization).toBe('Bearer tok_ok')
        await close()
        await closePairs(pairs)
    })

    it('stamps Authorization: Bearer <token> when auth.integration is set and the validator allows the host', async () => {
        const { factory, pairs, targets } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'linear',
                url: 'https://example.com/linear',
                secrets: [],
                auth: { integration: 'linear:T01' },
            },
        ]
        const { close } = await openMcpClients(refs, {
            integrations: {
                'linear:T01': { kind: 'linear', access_token: 'tok_abc' },
            },
            secrets: {},
            transportFactory: factory,
            integrationHostValidator: () => true,
        })
        expect(targets[0].headers).toEqual({ Authorization: 'Bearer tok_abc' })
        await close()
        await closePairs(pairs)
    })

    it('SECURITY: refuses to attach integration bearer when no host validator is wired (reported as unavailable)', async () => {
        // Fail-closed: a deploy that doesn't wire `integrationHostValidator`
        // must NOT silently regress to "attach bearer to whatever URL the
        // spec author chose." Without this, a malicious author could point
        // at their own URL and harvest the team's OAuth token. The MCP is
        // captured as unavailable (degraded session) rather than thrown so
        // a deploy regression on ONE integration doesn't blow up every
        // session that references it — the bearer is still NEVER attached.
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'linear',
                url: 'https://example.com/linear',
                secrets: [],
                auth: { integration: 'linear:T01' },
            },
        ]
        const { clients, close, failures } = await openMcpClients(refs, {
            integrations: { 'linear:T01': { kind: 'linear', access_token: 'tok_abc' } },
            secrets: {},
            transportFactory: factory,
        })
        expect(clients).toEqual([])
        expect(failures[0].category).toBe('auth')
        expect(failures[0].devReason).toMatch(/mcp_integration_host_validator_not_wired: linear:T01/)
        await close()
        await closePairs(pairs)
    })

    it('SECURITY: refuses to attach integration bearer when validator rejects the host (reported as unavailable)', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'linear',
                url: 'https://evil.example.com/linear',
                secrets: [],
                auth: { integration: 'linear:T01' },
            },
        ]
        const { clients, close, failures } = await openMcpClients(refs, {
            integrations: { 'linear:T01': { kind: 'linear', access_token: 'tok_abc' } },
            secrets: {},
            transportFactory: factory,
            integrationHostValidator: (ref, url) =>
                // Mimic a prod validator that only allows the canonical
                // host for a known integration kind.
                ref === 'linear:T01' && url.host === 'mcp.linear.app',
        })
        expect(clients).toEqual([])
        expect(failures[0].category).toBe('auth')
        expect(failures[0].devReason).toMatch(/mcp_integration_host_not_allowed: linear:T01 → evil\.example\.com/)
        await close()
        await closePairs(pairs)
    })

    it('SECURITY: refuses to attach integration bearer over plaintext http (reported as unavailable)', async () => {
        // Smokescreen owns SSRF but filters by destination, not scheme — it
        // won't stop the team's OAuth bearer being sent in cleartext to an
        // allowlisted public host. The host validator only checks `url.host`,
        // so the https-only guard is the runner's job on the credential path.
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'linear',
                url: 'http://mcp.linear.app/linear',
                secrets: [],
                auth: { integration: 'linear:T01' },
            },
        ]
        const { clients, close, failures } = await openMcpClients(refs, {
            integrations: { 'linear:T01': { kind: 'linear', access_token: 'tok_abc' } },
            secrets: {},
            transportFactory: factory,
            // Host is allowed — only the scheme should reject it.
            integrationHostValidator: () => true,
        })
        expect(clients).toEqual([])
        expect(failures[0].category).toBe('auth')
        expect(failures[0].devReason).toMatch(/mcp_integration_unsafe_scheme: linear:T01 → http:/)
        await close()
        await closePairs(pairs)
    })

    it('reports mcp_integration_not_resolved as an unavailable MCP (auth category)', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [
            {
                id: 'linear',
                url: 'https://example.com/linear',
                secrets: [],
                auth: { integration: 'linear:T01' },
            },
        ]
        const { clients, close, failures } = await openMcpClients(refs, {
            integrations: {},
            secrets: {},
            transportFactory: factory,
        })
        expect(clients).toEqual([])
        expect(failures[0].category).toBe('auth')
        expect(failures[0].devReason).toMatch(/mcp_integration_not_resolved: linear:T01/)
        await close()
        await closePairs(pairs)
    })

    it('on partial open: keeps the successful clients alive and records the bad ones as failures', async () => {
        const { factory, pairs, targets } = await buildEchoFactory()
        // First ref opens cleanly; second ref fails during target resolution
        // (missing integration). Under the degraded-MCP contract the session
        // continues with `ok`, and `broken` is reported via `failures`.
        const refs: McpRef[] = [
            { id: 'ok', url: 'https://example.com/a', secrets: [] },
            {
                id: 'broken',
                url: 'https://example.com/b',
                secrets: [],
                auth: { integration: 'missing' },
            },
        ]
        const { clients, close, failures } = await openMcpClients(refs, {
            integrations: {},
            secrets: {},
            transportFactory: factory,
        })
        expect(clients.map((c) => c.prefix)).toEqual(['ok'])
        expect(failures).toHaveLength(1)
        expect(failures[0].ref.id).toBe('broken')
        expect(failures[0].category).toBe('auth')
        expect(failures[0].devReason).toMatch(/mcp_integration_not_resolved/)
        expect(targets.length).toBeGreaterThanOrEqual(1)
        // The good client is still usable.
        const okPair = pairs[0]
        expect(okPair).not.toBeUndefined()
        expect(okPair.serverClosed.value).toBe(false)
        await close()
        // close() shut down the surviving client.
        expect(okPair.serverClosed.value).toBe(true)
        await closePairs(pairs)
    })

    it('surfaces remote tool errors as isError on the McpCallResult', async () => {
        const { factory, pairs } = await buildEchoFactory()
        const refs: McpRef[] = [{ id: 'echo', url: 'https://example.com/mcp', secrets: [] }]
        const { clients, close } = await openMcpClients(refs, {
            integrations: {},
            secrets: {},
            transportFactory: factory,
        })
        const result = await clients[0].callTool('boom', {})
        // The SDK shapes thrown handler errors as `{ content: [...], isError: true }`
        // instead of rejecting — buildAgentTools (PR 3) is what decides to turn
        // that into a thrown error for the loop.
        expect(result.isError).toBe(true)
        await close()
        await closePairs(pairs)
    })

    it('uses the prefix on log warnings when close fails', async () => {
        const warnings: Array<{ msg: string; meta?: Record<string, unknown> }> = []
        // Override the factory so close() rejects — exercises the catch in
        // openOne's returned `close()` closure.
        const { factory: echoFactory, pairs } = await buildEchoFactory()
        const factory: McpTransportFactory = (target) => {
            const inner = echoFactory(target)
            // Wrap to override close — but only the client side, so the test
            // can still drain the in-memory pair via its own pairs[] entry.
            return new Proxy(inner, {
                get(t, prop, recv) {
                    if (prop === 'close') {
                        return async () => {
                            throw new Error('explode_on_close')
                        }
                    }
                    const v = Reflect.get(t, prop, recv)
                    return typeof v === 'function' ? v.bind(t) : v
                },
            }) as Transport
        }
        const refs: McpRef[] = [{ id: 'echo', url: 'https://example.com/mcp', secrets: [] }]
        const { clients, close } = await openMcpClients(refs, {
            integrations: {},
            secrets: {},
            transportFactory: factory,
            log: (level, msg, meta) => {
                if (level === 'warn') {
                    warnings.push({ msg, meta })
                }
            },
        })
        await clients[0].close()
        expect(warnings.some((w) => w.msg === 'mcp.close.failed' && w.meta?.prefix === 'echo')).toBe(true)
        // Calling close() again via the batched closer just re-runs the same
        // path; we already asserted the per-client closure logged once.
        await close()
        await closePairs(pairs)
    })

    describe('devMcpBearerToken (dev-only auth fallback)', () => {
        it('attaches Authorization: Bearer when ref has no auth and a dev bearer is configured', async () => {
            const { factory, pairs, targets } = await buildEchoFactory()
            const { close } = await openMcpClients([{ id: 'x', url: 'https://mcp.example.com/sse', secrets: [] }], {
                integrations: {},
                secrets: {},
                transportFactory: factory,
                devMcpBearerToken: 'phx_dev_token',
            })
            expect(targets[0].headers.Authorization).toBe('Bearer phx_dev_token')
            await close()
            await closePairs(pairs)
        })

        it('does NOT attach the dev bearer when ref.auth.integration is set (integration wins)', async () => {
            const { factory, pairs, targets } = await buildEchoFactory()
            const ref: McpRef = {
                id: 'x',
                url: 'https://mcp.example.com/sse',
                secrets: [],
                auth: { integration: 'linear:acme' },
            }
            const { close } = await openMcpClients([ref], {
                integrations: { 'linear:acme': { access_token: 'integration_token', kind: 'linear' } },
                secrets: {},
                transportFactory: factory,
                devMcpBearerToken: 'phx_dev_token',
                integrationHostValidator: () => true,
            })
            expect(targets[0].headers.Authorization).toBe('Bearer integration_token')
            await close()
            await closePairs(pairs)
        })

        it('omits Authorization entirely when neither auth.integration nor a dev bearer is set', async () => {
            const { factory, pairs, targets } = await buildEchoFactory()
            const { close } = await openMcpClients([{ id: 'x', url: 'https://mcp.example.com/sse', secrets: [] }], {
                integrations: {},
                secrets: {},
                transportFactory: factory,
            })
            expect(targets[0].headers.Authorization).toBeUndefined()
            await close()
            await closePairs(pairs)
        })
    })
})
