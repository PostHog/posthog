/**
 * Generic HTTP client tool — POST/PUT/PATCH/DELETE/GET against arbitrary URLs.
 *
 * Use this for any HTTP API where the platform doesn't ship a typed native
 * tool: Slack chat.postMessage, GitHub REST, Linear, internal services, etc.
 * The author pastes their bearer/PAT into `spec.secrets[]` (via the
 * concierge's `set_secret` flow) and references it by name as `${TOKEN}` in
 * `url` / `headers` / `body`; the substitution happens server-side so the
 * plaintext value never appears in the model's tool-call history.
 *
 * Auth / SSRF stance — identical to `@posthog/web-fetch`:
 *   - SSRF protection is enforced at the egress hop by smokescreen (see
 *     `charts/shared/agent-platform/common.yaml`). The runner doesn't try to
 *     vet hostnames; smokescreen denies RFC1918 / loopback / cloud IMDS and
 *     re-resolves DNS per-IP at connect time.
 *   - The tool itself has no concept of integrations. If the agent author
 *     wants the platform-managed OAuth path (shared bot identity, central
 *     token rotation), use the typed `@posthog/slack-*` tools instead.
 *
 * Why this isn't just web-fetch with a method param: response bodies for
 * mutation calls (Slack, GitHub) carry useful payloads the model needs to
 * inspect (`{ok: true, ts: '17...'}`), and request bodies are first-class
 * inputs. The schema is a superset of web-fetch but the surface is wide
 * enough that keeping them separate makes the description clearer to the
 * model — `web-fetch` is for "read a page," `http-request` is for "call an
 * API."
 */

import { defineNativeTool, secretHostMatches, type ToolContext, Type } from '@posthog/agent-shared'

import { parseFetchableUrl } from './http-url'

const SECRET_REF = /\$\{([A-Z][A-Z0-9_]*)\}/g

/**
 * Resolve a `${NAME}` reference to its plaintext value, gated by the secret's
 * declared host binding. The `host` argument is the FINAL URL host the request
 * will land on after URL substitution; we validate every secret reference
 * against it before substituting, so a prompt-injected attacker URL can't
 * exfiltrate a credential the model has been told to "send to slack.com."
 *
 * Failure modes (all surfaced as throw, never silent):
 *   - `secret_not_resolved`     — name isn't in `spec.secrets[]` at all.
 *   - `secret_no_host_binding`  — name is a bare-string entry (declared but
 *                                 not pinned to any host).
 *   - `secret_host_not_allowed` — host isn't in the secret's allowlist.
 *
 * The bare-string refusal mirrors `mcp-clients.ts`'s unwired-validator
 * branch: declared-but-unbound credentials fail closed.
 */
function resolveSecretForHost(name: string, host: string, ctx: ToolContext): string {
    const value = ctx.secret(name)
    if (value === undefined) {
        throw new Error(`secret_not_resolved: ${name}`)
    }
    const allowed = ctx.secretAllowedHosts(name)
    if (allowed === null) {
        throw new Error(`secret_no_host_binding: ${name}`)
    }
    if (allowed === undefined) {
        throw new Error(`secret_not_resolved: ${name}`)
    }
    if (!allowed.some((pattern) => secretHostMatches(pattern, host))) {
        throw new Error(`secret_host_not_allowed: ${name} -> ${host}`)
    }
    return value
}

function substituteSecrets(input: string, host: string, ctx: ToolContext): string {
    return input.replace(SECRET_REF, (_match, name: string) => resolveSecretForHost(name, host, ctx))
}

/**
 * URL substitution is the chicken-and-egg case — we need the FINAL host to
 * validate any secrets used, but a secret may itself appear inside the host
 * (e.g. `https://${TENANT}.example.com/api`). Two-pass:
 *   1. Compute the post-substitution URL using the secret values WITHOUT
 *      validating allowed_hosts yet (we don't know the host yet).
 *   2. Parse the final URL, extract its host, and revalidate: for each secret
 *      referenced, the resolved host must be in that secret's allowlist.
 *
 * The first pass still enforces existence (`secret_not_resolved`) and rejects
 * bare-string declarations (`secret_no_host_binding`) — those errors don't
 * depend on knowing the host. Only the host-allowlist check is deferred.
 */
function substituteUrlAndExtractHost(
    template: string,
    ctx: ToolContext
): { url: string; host: string; referenced: ReadonlySet<string> } {
    const referenced = new Set<string>()
    const substituted = template.replace(SECRET_REF, (_match, name: string) => {
        referenced.add(name)
        const value = ctx.secret(name)
        if (value === undefined) {
            throw new Error(`secret_not_resolved: ${name}`)
        }
        const allowed = ctx.secretAllowedHosts(name)
        if (allowed === null) {
            throw new Error(`secret_no_host_binding: ${name}`)
        }
        if (allowed === undefined) {
            throw new Error(`secret_not_resolved: ${name}`)
        }
        return value
    })
    const parsed = parseFetchableUrl(substituted)
    const host = parsed.host
    for (const name of referenced) {
        const allowed = ctx.secretAllowedHosts(name) as readonly string[]
        if (!allowed.some((pattern) => secretHostMatches(pattern, host))) {
            throw new Error(`secret_host_not_allowed: ${name} -> ${host}`)
        }
    }
    return { url: substituted, host, referenced }
}

function substituteHeaders(
    headers: Record<string, string> | undefined,
    host: string,
    ctx: ToolContext
): Record<string, string> {
    if (!headers) {
        return {}
    }
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries(headers)) {
        out[k] = substituteSecrets(v, host, ctx)
    }
    return out
}

/**
 * Serialize `body` for the wire. Object → JSON + `Content-Type: application/json`
 * unless the caller already set a content-type header. String passes through
 * verbatim. Undefined → no body sent.
 *
 * Secret substitution happens AFTER serialization so a token can live inside
 * a JSON value (e.g. `{"token": "${SLACK_BOT_TOKEN}"}`) without the author
 * having to think about escaping.
 */
function serializeBody(
    body: string | Record<string, unknown> | undefined,
    headers: Record<string, string>,
    host: string,
    ctx: ToolContext
): { body: string | undefined; headers: Record<string, string> } {
    if (body === undefined) {
        return { body: undefined, headers }
    }
    if (typeof body === 'string') {
        return { body: substituteSecrets(body, host, ctx), headers }
    }
    const hasContentType = Object.keys(headers).some((k) => k.toLowerCase() === 'content-type')
    const finalHeaders = hasContentType ? headers : { ...headers, 'Content-Type': 'application/json; charset=utf-8' }
    return { body: substituteSecrets(JSON.stringify(body), host, ctx), headers: finalHeaders }
}

const DEFAULT_MAX_RESPONSE_BYTES = 1_000_000
const ABSOLUTE_MAX_RESPONSE_BYTES = 5_000_000
const DEFAULT_TIMEOUT_MS = 15_000
const ABSOLUTE_MAX_TIMEOUT_MS = 60_000

/**
 * Read the response body up to `maxBytes`, streaming so an oversized or
 * highly-compressed response is never fully materialized before truncation.
 * Stops at the cap and cancels the stream, which tears down the underlying
 * connection so we don't keep pulling bytes we'll throw away. Falls back to
 * `res.text()` only when the response exposes no readable stream (e.g. an
 * empty body or a non-streaming test mock), still capping the result.
 */
async function readCappedBody(
    res: Response,
    maxBytes: number
): Promise<{ body: string; bytesRead: number; truncated: boolean }> {
    const stream = res.body
    if (!stream) {
        const text = await res.text()
        const bytes = new TextEncoder().encode(text)
        if (bytes.byteLength <= maxBytes) {
            return { body: text, bytesRead: bytes.byteLength, truncated: false }
        }
        return { body: new TextDecoder().decode(bytes.subarray(0, maxBytes)), bytesRead: maxBytes, truncated: true }
    }

    const reader = stream.getReader()
    const chunks: Uint8Array[] = []
    let total = 0
    let truncated = false
    try {
        while (total < maxBytes) {
            const { done, value } = await reader.read()
            if (done) {
                break
            }
            if (total + value.byteLength > maxBytes) {
                chunks.push(value.subarray(0, maxBytes - total))
                total = maxBytes
                truncated = true
                break
            }
            chunks.push(value)
            total += value.byteLength
        }
    } finally {
        // Cancel rather than drain: releases the socket so we never pull past the cap.
        await reader.cancel().catch(() => {})
    }

    const buf = new Uint8Array(total)
    let offset = 0
    for (const chunk of chunks) {
        buf.set(chunk, offset)
        offset += chunk.byteLength
    }
    return { body: new TextDecoder().decode(buf), bytesRead: total, truncated }
}

export const httpRequestV1 = defineNativeTool({
    id: '@posthog/http-request',
    // Proxy-bound (smokescreen blocks internal SSRF) and author-opt-in — gating
    // every outbound call would make integration automation unusable, so allow.
    approval: 'allow',
    description: [
        'Make an arbitrary HTTP request (GET/POST/PUT/PATCH/DELETE) against a URL.',
        'Use this for any service where the platform does not ship a typed tool —',
        "Slack's Web API, GitHub REST, Linear, internal services, etc. Reference",
        'secrets declared in `spec.secrets` as `${NAME}` inside url, headers, or',
        'body; the runner substitutes the plaintext value before the request goes',
        "out, so the token never appears in the model's tool-call history.",
    ].join(' '),
    args: Type.Object({
        url: Type.String({
            format: 'uri',
            description:
                'Target URL. May contain `${NAME}` placeholders that resolve from spec.secrets. ' +
                "Secrets only substitute when the URL host is in that secret's declared `allowed_hosts`.",
        }),
        method: Type.Optional(
            Type.Union(
                [
                    Type.Literal('GET'),
                    Type.Literal('POST'),
                    Type.Literal('PUT'),
                    Type.Literal('PATCH'),
                    Type.Literal('DELETE'),
                ],
                { default: 'GET', description: 'HTTP method. Default GET.' }
            )
        ),
        headers: Type.Optional(
            Type.Record(Type.String(), Type.String(), {
                description:
                    'Request headers. Values may contain `${NAME}` placeholders. Authorization headers are the typical use case.',
            })
        ),
        body: Type.Optional(
            Type.Union([Type.String(), Type.Record(Type.String(), Type.Unknown())], {
                description:
                    'Request body. Strings are sent verbatim; objects are JSON-encoded and Content-Type defaults to application/json. For form-encoded (or any non-JSON) APIs, pass a pre-encoded string body and set Content-Type yourself. `${NAME}` placeholders work inside either form.',
            })
        ),
        timeout_ms: Type.Optional(
            Type.Integer({
                minimum: 1,
                maximum: ABSOLUTE_MAX_TIMEOUT_MS,
                description: `Per-request timeout in ms (default ${DEFAULT_TIMEOUT_MS}, max ${ABSOLUTE_MAX_TIMEOUT_MS}).`,
            })
        ),
        max_response_bytes: Type.Optional(
            Type.Integer({
                minimum: 1,
                maximum: ABSOLUTE_MAX_RESPONSE_BYTES,
                description: `Cap on response body bytes returned to the model (default ${DEFAULT_MAX_RESPONSE_BYTES}, max ${ABSOLUTE_MAX_RESPONSE_BYTES}). Bodies larger than this are truncated.`,
            })
        ),
    }),
    returns: Type.Object({
        status: Type.Number(),
        body: Type.String(),
        content_type: Type.String(),
        /** Selected response headers — model rarely needs more than a handful. */
        headers: Type.Record(Type.String(), Type.String()),
        url: Type.String(),
        truncated: Type.Boolean({ description: 'True if the response body was clipped to max_response_bytes.' }),
    }),
    requires: {},
    cost_hint: 'medium',
    async run(args, ctx) {
        // URL is substituted first so we know the FINAL host; every secret
        // referenced in url/headers/body is then validated against that host
        // via `spec.secrets[].allowed_hosts`. Refuses if the URL parses to a
        // non-http(s) scheme (same guard as before — smokescreen owns host /
        // IP filtering).
        const { url, host } = substituteUrlAndExtractHost(args.url, ctx)
        const method = args.method ?? 'GET'
        const headersIn = substituteHeaders(args.headers, host, ctx)
        const { body, headers: finalHeaders } = serializeBody(args.body, headersIn, host, ctx)
        const maxBytes = args.max_response_bytes ?? DEFAULT_MAX_RESPONSE_BYTES
        const timeoutMs = args.timeout_ms ?? DEFAULT_TIMEOUT_MS

        const controller = new AbortController()
        const abortTimer = setTimeout(() => controller.abort(), timeoutMs)

        let res: Response
        try {
            res = await ctx.http.fetch(url, {
                method,
                headers: finalHeaders,
                body,
                signal: controller.signal,
            })
        } catch (err) {
            const e = err as Error & { name?: string }
            if (e.name === 'AbortError') {
                throw new Error(`http_request_timeout: ${timeoutMs}ms`)
            }
            throw new Error(`http_request_failed: ${e.message ?? 'unknown'}`)
        } finally {
            clearTimeout(abortTimer)
        }

        const { body: bodyOut, bytesRead, truncated } = await readCappedBody(res, maxBytes)

        // Surface a small fixed set of useful response headers; sending every
        // header back inflates the context for no model-side payoff.
        const HEADER_ALLOWLIST = new Set(['content-type', 'content-length', 'location', 'retry-after', 'date'])
        const headersOut: Record<string, string> = {}
        for (const [k, v] of res.headers.entries()) {
            if (HEADER_ALLOWLIST.has(k.toLowerCase())) {
                headersOut[k] = v
            }
        }

        ctx.log('info', 'http.request.completed', {
            method,
            url,
            status: res.status,
            response_bytes: bytesRead,
            truncated,
        })

        return {
            status: res.status,
            body: bodyOut,
            content_type: res.headers.get('content-type') ?? '',
            headers: headersOut,
            url,
            truncated,
        }
    },
})
