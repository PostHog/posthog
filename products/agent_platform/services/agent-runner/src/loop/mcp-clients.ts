/**
 * Open MCP clients for an agent's `spec.mcps[]` at session start. Each opened
 * client carries:
 *   - `prefix` — the model-visible name prefix (`<prefix>__<remoteToolName>`).
 *   - `listTools()` — list of remote tools (used by `buildAgentTools` to emit
 *     one `AgentTool` per remote tool).
 *   - `callTool(name, args)` — invoke; result is the raw MCP `CallToolResult`.
 *     `buildAgentTools` owns the translation into `AgentToolResult`.
 *   - `close()` — best-effort transport shutdown.
 *
 * Auth resolution:
 *   - `auth.integration` → `integrations[ref].access_token` →
 *     `Authorization: Bearer <token>`. Host-bound by the worker's
 *     `integrationHostValidator` so a spec author can't redirect a team's
 *     OAuth token to an arbitrary URL.
 *   - `secrets[]` → resolve each name via `secrets[NAME]`; substitute
 *     `${NAME}` placeholders in the URL + author-supplied headers before
 *     opening the transport. Each substitution is gated on the secret's
 *     declared `spec.secrets[].allowed_hosts` against the FINAL request host
 *     (via `secretAllowedHosts`), identical to `@posthog/http-request`: a
 *     bare-string (unbound) secret fails closed, and a host outside the
 *     secret's allowlist is refused before the value is ever stamped onto the
 *     wire. Without this an author could set `headers.Authorization = 'Bearer
 *     ${SLACK_BOT_TOKEN}'` and point `url` at a host they control, exfiltrating
 *     an encrypted-env secret they otherwise can't read.
 *
 * Failure during open: a single ref failing to connect (transport error,
 * upstream 401, auth resolution issue) no longer kills the session. The
 * function returns `{ clients, close, failures }` — `clients` is the
 * successfully-opened subset and `failures` carries per-ref categorisation
 * so the agent's system prompt can tell the model which capabilities are
 * temporarily unavailable. Only `duplicate_mcp_prefix` (a spec-author
 * conflict that breaks model-visible tool naming) is still thrown — the
 * runner has no graceful fallback when two refs collide.
 *
 * NOT in scope for this module: tool-name prefixing (the caller composes
 * `${prefix}__${toolName}`), inclusion filtering via `ref.tools[]` (the
 * caller iterates `listTools()` and skips entries not in the names projected
 * from `ref.tools`), or the per-tool approval wrap (driver looks the policy
 * up via `mcp-tool-lookup.ts`). Keeping those concerns in `buildAgentTools`
 * + `driver` matches how native/custom tools already work.
 */

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js'

import { HttpFetcher, IntegrationCredentials, McpRef, secretHostMatches } from '@posthog/agent-shared'

/** Remote tool descriptor as returned by `client.listTools()`. */
export interface RemoteMcpTool {
    name: string
    description: string
    /**
     * JSON Schema fragment. `buildAgentTools` (PR 3) casts this to pi-ai's
     * `TSchema` — same as the existing `kind: 'client'` tool path does for
     * author-supplied schemas. The SDK guarantees a `{ type: 'object', ... }`
     * shape per the MCP protocol.
     */
    inputSchema: unknown
}

/** Raw MCP `CallToolResult` — `buildAgentTools` shapes this into an
 *  `AgentToolResult` and decides how to surface `isError` to the model. */
export type McpCallResult = Awaited<ReturnType<Client['callTool']>>

export interface OpenedMcp {
    /** Tool-name prefix at runtime: `<prefix>__<remoteToolName>`. */
    prefix: string
    /** The original spec ref this client was opened for. Handy for logging
     *  and for the caller to inspect `tools[]` per tool. */
    ref: McpRef
    listTools(): Promise<RemoteMcpTool[]>
    callTool(name: string, args: Record<string, unknown>): Promise<McpCallResult>
    close(): Promise<void>
}

/**
 * Coarse failure-cause buckets surfaced to the agent's system prompt so the
 * model can tell the user *what kind of thing* is wrong (without the raw
 * upstream error string, which often leaks transport URLs / docs links /
 * provider-side stack hints). The agent owner gets the full reason via
 * log_entries.
 *   - `auth`      — credentials / token / secret resolution problem
 *                   (`mcp_secret_not_resolved`, `mcp_integration_*`,
 *                   401/403 from the remote)
 *   - `network`   — couldn't reach the server (DNS, refused, timeout, 5xx)
 *   - `not_found` — server responded but said the endpoint is gone (404, 410)
 *   - `unknown`   — anything else; default bucket for novel transport errors
 */
export type McpFailureCategory = 'auth' | 'network' | 'not_found' | 'unknown'

export interface McpOpenFailure {
    ref: McpRef
    category: McpFailureCategory
    /** The raw error message. Server-side observability only — never to be
     *  forwarded to the chat UI or the model's view of the world. The agent
     *  owner reads this via `log_entries` on the session detail page. */
    devReason: string
}

/**
 * Heuristic classifier — string-matching against the error message is
 * brittle, but every alternative (typed errors, status codes everywhere)
 * requires touching every transport library + auth resolver in the stack.
 * The category never feeds back into runtime behaviour; it only shapes the
 * one user-visible sentence in the system prompt, so a mis-categorisation
 * degrades to "unavailable (unknown reason)" rather than a real bug.
 */
export function categorizeMcpOpenError(err: Error): McpFailureCategory {
    const msg = err.message.toLowerCase()
    if (
        msg.includes('mcp_secret_') ||
        msg.includes('mcp_integration_') ||
        msg.includes('no token') ||
        msg.includes('unauthor') ||
        msg.includes(' 401') ||
        msg.includes(' 403') ||
        msg.includes('forbidden') ||
        msg.includes('invalid api key') ||
        msg.includes('invalid token')
    ) {
        return 'auth'
    }
    if (msg.includes(' 404') || msg.includes('not found') || msg.includes('gone')) {
        return 'not_found'
    }
    if (
        msg.includes('econnrefused') ||
        msg.includes('etimedout') ||
        msg.includes('enotfound') ||
        msg.includes('eai_again') ||
        msg.includes('network') ||
        msg.includes('timeout') ||
        msg.includes('502') ||
        msg.includes('503') ||
        msg.includes('504') ||
        msg.includes('connection')
    ) {
        return 'network'
    }
    return 'unknown'
}

/**
 * Factory for the underlying SDK transport. Defaults to
 * `StreamableHTTPClientTransport`. Tests override with a factory that pairs
 * with an in-process `McpServer` via `InMemoryTransport.createLinkedPair()`.
 */
export type McpTransportFactory = (target: { url: string; headers: Record<string, string> }) => Transport

/**
 * Per-call validator the runner consults before stamping a connected
 * integration's bearer token on an outbound MCP request. Returns `true` to
 * allow attachment, `false` to reject. The worker is expected to wire a
 * validator that maps the integration kind (e.g. `linear`, `github`) to
 * the host pattern that integration is authorised for; without a wired
 * validator, every `auth.integration`-bearing ref is **refused at open
 * time** so a malicious spec author can't redirect a team's OAuth token
 * to an arbitrary URL.
 */
export type IntegrationHostValidator = (integrationRef: string, url: URL) => boolean

export interface OpenMcpClientsDeps {
    integrations: Record<string, IntegrationCredentials>
    /** Resolved plaintext secrets keyed by name (same shape `runSession`
     *  already threads through). Only the names listed on a given ref's
     *  `secrets[]` are substituted into that ref's URL. */
    secrets: Record<string, string>
    /**
     * Resolve a secret's declared `allowed_hosts` binding by name — the worker
     * wires `(name) => getSecretAllowedHosts(spec, name)`. Three-way return:
     *   - `string[]`  — secret pinned to these hosts.
     *   - `null`      — declared as a bare string (no host binding); fail closed.
     *   - `undefined` — not declared in `spec.secrets[]` at all.
     * Gates every `${NAME}` substitution in the MCP URL + headers on the FINAL
     * request host, identical to `@posthog/http-request`. Fail-closed when
     * unset: any referenced secret is treated as unbound, so a deploy that
     * forgets to wire this can't silently regress to "send the secret to any
     * host." See `SecretRefSchema` for the binding shape + threat model.
     */
    secretAllowedHosts?: (name: string) => readonly string[] | null | undefined
    transportFactory?: McpTransportFactory
    log?: (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>) => void
    /** Identity sent during the MCP `initialize` handshake. Defaults to the
     *  runner's own name + a static version stamp. */
    clientInfo?: { name: string; version: string }
    /**
     * Validator that decides whether a connected integration's bearer token
     * may be attached to a given MCP URL. Fail-closed: when unset, any
     * `auth.integration`-bearing external ref is refused at open time
     * (`mcp_integration_host_validator_not_wired`). See the type definition
     * for the threat model.
     */
    integrationHostValidator?: IntegrationHostValidator
    /**
     * Dev-only bearer attached to `kind: external` MCP requests when the
     * ref has no `auth.integration` of its own (`ref.auth` wins if set).
     * Bridges the local-dev auth gap until external-MCP credentials are
     * sourced from the per-session credential broker. Production refuses
     * to set this at boot.
     */
    devMcpBearerToken?: string
    /**
     * Outbound HTTP client. Passed as the SDK transport's `fetch` option so
     * MCP traffic dispatches through the same proxy as native tools (in
     * prod that's smokescreen). When omitted, the SDK uses its built-in
     * global `fetch` — fine for tests, never set in prod.
     */
    http?: HttpFetcher
}

const DEFAULT_CLIENT_INFO = { name: 'posthog-agent-runner', version: '0.1.0' }

const noopLog: NonNullable<OpenMcpClientsDeps['log']> = () => {}

function makeDefaultTransportFactory(http?: HttpFetcher): McpTransportFactory {
    // Bind ahead of time so each transport call dispatches through the same
    // HttpClient — undefined falls back to the SDK's built-in global fetch.
    const boundFetch = http ? http.fetch.bind(http) : undefined
    return ({ url, headers }) =>
        new StreamableHTTPClientTransport(new URL(url), {
            requestInit: { headers },
            ...(boundFetch ? { fetch: boundFetch } : {}),
        })
}

/**
 * Open one MCP client per entry in `refs`, returning a stable list plus a
 * batched `close()` callable from the worker's `finally`. See module header
 * for failure semantics + auth resolution.
 */
export async function openMcpClients(
    refs: readonly McpRef[],
    deps: OpenMcpClientsDeps
): Promise<{ clients: OpenedMcp[]; close: () => Promise<void>; failures: McpOpenFailure[] }> {
    if (refs.length === 0) {
        return { clients: [], close: async () => {}, failures: [] }
    }

    const log = deps.log ?? noopLog
    const transportFactory = deps.transportFactory ?? makeDefaultTransportFactory(deps.http)
    const clientInfo = deps.clientInfo ?? DEFAULT_CLIENT_INFO

    // Parallel open — N refs would otherwise stack N round-trips at session
    // start. `allSettled` so a partial-open doesn't leak the successful
    // clients. Per-ref failures are kept and surfaced via `failures`; the
    // session continues with the subset that did open.
    const results = await Promise.allSettled(
        refs.map((ref) => openOne(ref, { ...deps, transportFactory, clientInfo, log }))
    )

    const opened: OpenedMcp[] = []
    const failures: McpOpenFailure[] = []
    for (let i = 0; i < results.length; i++) {
        const r = results[i]
        if (r.status === 'fulfilled') {
            opened.push(r.value)
            continue
        }
        const err = r.reason instanceof Error ? r.reason : new Error(String(r.reason))
        const ref = refs[i]
        const category = categorizeMcpOpenError(err)
        failures.push({ ref, category, devReason: err.message })
        log('warn', 'mcp.open.failed', { prefix: ref.id, category, devReason: err.message })
    }

    // Duplicate prefix = the model would see two tools with the same fully
    // qualified name. This is a spec-author conflict the runner has no
    // graceful fallback for — surface loudly rather than silently shadowing
    // one. Closing already-opened clients on the way out matches the
    // historical contract.
    const prefixes = new Set<string>()
    for (const o of opened) {
        if (prefixes.has(o.prefix)) {
            await closeAll(opened, log)
            throw new Error(`duplicate_mcp_prefix: ${o.prefix}`)
        }
        prefixes.add(o.prefix)
    }

    return {
        clients: opened,
        close: async () => closeAll(opened, log),
        failures,
    }
}

interface OpenOneDeps extends OpenMcpClientsDeps {
    transportFactory: McpTransportFactory
    clientInfo: { name: string; version: string }
    log: NonNullable<OpenMcpClientsDeps['log']>
}

async function openOne(ref: McpRef, deps: OpenOneDeps): Promise<OpenedMcp> {
    const target = await resolveTarget(ref, deps)
    const transport = deps.transportFactory(target)
    const client = new Client(deps.clientInfo, { capabilities: {} })
    await client.connect(transport)

    const prefix = ref.id
    return {
        prefix,
        ref,
        listTools: async () => {
            const res = await client.listTools()
            return res.tools.map((t) => ({
                name: t.name,
                description: t.description ?? '',
                inputSchema: t.inputSchema,
            }))
        },
        callTool: async (name, args) => client.callTool({ name, arguments: args }),
        close: async () => {
            try {
                await client.close()
            } catch (err) {
                deps.log('warn', 'mcp.close.failed', { prefix, err: (err as Error).message })
            }
        },
    }
}

async function resolveTarget(
    ref: McpRef,
    deps: OpenMcpClientsDeps
): Promise<{ url: string; headers: Record<string, string> }> {
    // SSRF protection is handled at the infra layer by smokescreen (see
    // charts/shared/agent-platform/common.yaml `httpProxy.enabled: true`).
    // Author chose the URL; smokescreen denies RFC1918 / loopback /
    // link-local / cloud-IMDS + closes the DNS-rebinding gap via per-IP
    // resolution at connect time. The runner only handles the logical-binding
    // check (integration → host allowlist), which smokescreen can't do.
    //
    // Fail-closed when the host lookup isn't wired: treat every secret as
    // unbound so substitution refuses rather than sending it to any host.
    const allowedHostsFor = deps.secretAllowedHosts ?? (() => null)
    // URL is substituted first so we know the FINAL host; every `${NAME}` in the
    // URL + headers is then validated against that host via the secret's
    // `allowed_hosts`, so an author can't point `url` at a host they control and
    // exfiltrate a secret stamped into a header. Same shape as
    // `@posthog/http-request`'s URL-first host binding.
    const { url, host } = substituteUrlAndExtractHost(ref.url, ref.secrets, allowedHostsFor, deps.secrets)
    const headers: Record<string, string> = {}
    if (ref.auth?.integration) {
        const cred = deps.integrations[ref.auth.integration]
        if (!cred) {
            throw new Error(`mcp_integration_not_resolved: ${ref.auth.integration}`)
        }
        // Fail-closed integration host binding: an author can't redirect a
        // team's OAuth token to an arbitrary URL because the worker's
        // validator gates which host each integration kind is allowed to
        // talk to. The unwired-validator branch refuses unconditionally so
        // a config-drift / deploy issue can't silently regress to "attach
        // bearer to anything." See `IntegrationHostValidator` doc + the
        // PR-6 security thread.
        if (!deps.integrationHostValidator) {
            throw new Error(`mcp_integration_host_validator_not_wired: ${ref.auth.integration}`)
        }
        const parsed = new URL(url)
        // Smokescreen owns SSRF, but it can't guarantee the OAuth bearer isn't
        // sent in cleartext to an allowlisted public host — it filters by
        // destination, not scheme. The host validator below only checks
        // `url.host`, so without this an author could set `http://api.slack.com`
        // and have the team's token stamped onto a plaintext request. Enforce
        // https on the credential path only; non-auth external URLs stay
        // smokescreen's concern.
        if (parsed.protocol !== 'https:') {
            throw new Error(`mcp_integration_unsafe_scheme: ${ref.auth.integration} → ${parsed.protocol}`)
        }
        if (!deps.integrationHostValidator(ref.auth.integration, parsed)) {
            throw new Error(`mcp_integration_host_not_allowed: ${ref.auth.integration} → ${parsed.host}`)
        }
        headers['Authorization'] = `Bearer ${cred.access_token}`
    } else if (deps.devMcpBearerToken) {
        // Dev-only fallback. The bundle declared no integration auth, but
        // the operator wired a global dev bearer (their PAT, typically) so
        // the local MCP server accepts the call. `ref.auth` always wins
        // when set; this branch only fires when the spec is auth-less.
        headers['Authorization'] = `Bearer ${deps.devMcpBearerToken}`
    }
    // Author-supplied headers — the BYO-bearer-token path. Walked after the
    // integration / dev-bearer blocks so explicit author entries take
    // precedence on duplicate keys (matches `http-request`'s "caller-set
    // values are not silently overwritten" rule). Each `${NAME}` is gated on
    // the secret's `allowed_hosts` against the final URL host — a header
    // secret can't be sent to a host the author isn't authorised for.
    if (ref.headers) {
        for (const [name, raw] of Object.entries(ref.headers)) {
            headers[name] = substituteSecretsForHost(raw, host, ref.secrets, allowedHostsFor, deps.secrets)
        }
    }
    return { url, headers }
}

type AllowedHostsFor = (name: string) => readonly string[] | null | undefined

/**
 * Resolve a single `${NAME}` reference to its plaintext value, gated by the
 * secret's declared host binding against `host` (the FINAL request host).
 * Mirrors `@posthog/http-request`'s `resolveSecretForHost`:
 *   - `mcp_secret_not_resolved`     — name isn't resolvable (missing value, or
 *                                      not declared in `spec.secrets[]`).
 *   - `mcp_secret_no_host_binding`  — name is a bare-string entry (declared but
 *                                      not pinned to any host); fail closed.
 *   - `mcp_secret_host_not_allowed` — host isn't in the secret's allowlist.
 */
function resolveSecretForHost(
    name: string,
    host: string,
    allowedHostsFor: AllowedHostsFor,
    available: Record<string, string>
): string {
    const value = available[name]
    if (value === undefined) {
        throw new Error(`mcp_secret_not_resolved: ${name}`)
    }
    const allowed = allowedHostsFor(name)
    if (allowed === null) {
        throw new Error(`mcp_secret_no_host_binding: ${name}`)
    }
    if (allowed === undefined) {
        throw new Error(`mcp_secret_not_resolved: ${name}`)
    }
    if (!allowed.some((pattern) => secretHostMatches(pattern, host))) {
        throw new Error(`mcp_secret_host_not_allowed: ${name} -> ${host}`)
    }
    return value
}

/**
 * Substitute `${NAME}` placeholders in `input` for each name listed on the
 * ref's `secrets[]`, gating each on the secret's `allowed_hosts` against
 * `host`. Used for author-supplied headers, where `host` is the already-known
 * final URL host.
 */
function substituteSecretsForHost(
    input: string,
    host: string,
    declared: readonly string[],
    allowedHostsFor: AllowedHostsFor,
    available: Record<string, string>
): string {
    let out = input
    for (const name of declared) {
        const token = `\${${name}}`
        if (!out.includes(token)) {
            continue
        }
        out = out.split(token).join(resolveSecretForHost(name, host, allowedHostsFor, available))
    }
    return out
}

/**
 * Substitute `${NAME}` placeholders in the URL and extract the final host. The
 * chicken-and-egg case (a secret may appear inside the host, e.g.
 * `https://${TENANT}.example.com`) forces two passes:
 *   1. Substitute referenced secrets, enforcing existence + the bare-string
 *      refusal (neither depends on knowing the host yet).
 *   2. Parse the final URL, extract its host, and revalidate every referenced
 *      secret's `allowed_hosts` against it.
 * Only names declared on the ref's `secrets[]` are substituted; a literal
 * `${FOO}` for an undeclared name is left untouched (matches prior behaviour).
 */
function substituteUrlAndExtractHost(
    template: string,
    declared: readonly string[],
    allowedHostsFor: AllowedHostsFor,
    available: Record<string, string>
): { url: string; host: string } {
    const referenced: string[] = []
    let url = template
    for (const name of declared) {
        const token = `\${${name}}`
        if (!url.includes(token)) {
            continue
        }
        const value = available[name]
        if (value === undefined) {
            throw new Error(`mcp_secret_not_resolved: ${name}`)
        }
        const allowed = allowedHostsFor(name)
        if (allowed === null) {
            throw new Error(`mcp_secret_no_host_binding: ${name}`)
        }
        if (allowed === undefined) {
            throw new Error(`mcp_secret_not_resolved: ${name}`)
        }
        referenced.push(name)
        url = url.split(token).join(value)
    }
    const host = new URL(url).host
    for (const name of referenced) {
        const allowed = allowedHostsFor(name) as readonly string[]
        if (!allowed.some((pattern) => secretHostMatches(pattern, host))) {
            throw new Error(`mcp_secret_host_not_allowed: ${name} -> ${host}`)
        }
    }
    return { url, host }
}

async function closeAll(opened: readonly OpenedMcp[], log: NonNullable<OpenMcpClientsDeps['log']>): Promise<void> {
    const results = await Promise.allSettled(opened.map((o) => o.close()))
    for (let i = 0; i < results.length; i++) {
        const r = results[i]
        if (r.status === 'rejected') {
            log('warn', 'mcp.close.batch_failed', {
                prefix: opened[i].prefix,
                err: r.reason instanceof Error ? r.reason.message : String(r.reason),
            })
        }
    }
}
