/**
 * GitHub REST client that authenticates as a GitHub App.
 *
 * Why a dedicated tool instead of `@posthog/http-request`: App auth requires
 * SIGNING an RS256 JWT with the App's private key and exchanging it for a
 * short-lived installation access token — a computation over the secret, not a
 * `${NAME}` pass-through, so header substitution can't express it. And custom
 * tools can't do it either: their sandbox has no network and only sees secret
 * nonces. The runner is the one place that legitimately holds plaintext
 * secrets and egress, so the mint happens here and neither the private key,
 * the JWT, nor the installation token ever reaches the model's context.
 *
 * The agent declares two secrets (author-set via the env editor):
 *   - `GITHUB_APP_ID`          — the App's numeric id
 *   - `GITHUB_APP_PRIVATE_KEY` — the App's PEM private key (PKCS#1 as GitHub
 *                                ships it, or PKCS#8; literal `\n` escapes from
 *                                copy-paste are tolerated)
 * Declare them as bare strings: this tool reads them directly, and the bare
 * form means `@posthog/http-request` refuses to substitute them anywhere.
 *
 * Egress is pinned to `https://api.github.com` — `path` is joined to that
 * base and re-validated after parsing, so a crafted path can't redirect the
 * minted token elsewhere. SSRF beyond that is smokescreen's job, same as
 * every proxy-bound tool.
 *
 * Blast-radius controls for an App installed across many orgs, where
 * `installation_id` and the repo path are model-controlled:
 *   - Minted tokens are down-scoped to the repo in the path (`repositories`),
 *     so a token only works on the resource being accessed.
 *   - An optional `GITHUB_APP_ALLOWED_OWNERS` secret restricts which accounts
 *     the tool may act on, refusing off-list requests before any mint.
 * The durable fix — binding the installation to the signature-verified trigger
 * payload instead of a model arg — is a platform change tracked separately.
 */

import { createHash, createPrivateKey, createSign, type KeyObject } from 'node:crypto'

import { defineNativeTool, type ToolContext, Type } from '@posthog/agent-shared'

import {
    ABSOLUTE_MAX_RESPONSE_BYTES,
    ABSOLUTE_MAX_TIMEOUT_MS,
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_TIMEOUT_MS,
    fetchWithTimeout,
    pickHeaders,
    readCappedBody,
} from './http-shared'

const API_BASE = 'https://api.github.com'
const API_HOST = 'api.github.com'
const API_VERSION = '2022-11-28'
const DEFAULT_ACCEPT = 'application/vnd.github+json'
const ERR_PREFIX = 'github_app_request'

export const GITHUB_APP_ID_SECRET = 'GITHUB_APP_ID'
export const GITHUB_APP_PRIVATE_KEY_SECRET = 'GITHUB_APP_PRIVATE_KEY'
/** Optional comma/space-separated list of GitHub account logins (orgs or users)
 *  the tool may act on. When set, a request whose path targets any other owner
 *  is refused before a token is minted — the durable guard for an App installed
 *  across many orgs, where installation_id and the repo path are otherwise
 *  model-controlled. Unset = no restriction. */
export const GITHUB_APP_ALLOWED_OWNERS_SECRET = 'GITHUB_APP_ALLOWED_OWNERS'

/** GitHub rejects App JWTs whose exp is more than 10 minutes out; stay well under. */
const JWT_TTL_SECONDS = 540
/** Backdate iat to absorb clock drift between us and GitHub (their documented recommendation). */
const JWT_CLOCK_DRIFT_SECONDS = 60

/** Response headers worth returning to the model — includes `link` for pagination. */
const HEADER_ALLOWLIST = new Set([
    'content-type',
    'link',
    'retry-after',
    'x-ratelimit-remaining',
    'x-ratelimit-reset',
    'date',
])

/** Re-mint when a cached token has less than this long left — installation
 *  tokens live 1h and a review session can outlast the tail of one. */
const TOKEN_REFRESH_MARGIN_MS = 5 * 60 * 1000
const TOKEN_CACHE_MAX_ENTRIES = 200

/**
 * Process-local mint cache. This module is shared across every session a
 * worker runs concurrently (different teams included), so the key MUST bind
 * the entry to proof of key possession, not just the public (app id,
 * installation id) pair — otherwise any agent declaring a victim's public App
 * id plus any parseable PEM could read a cached token it never had the key to
 * mint. The key fingerprint (a hash of the private key, never the key itself)
 * closes that: a different key yields a different cache slot, so a forged key
 * falls through to a real mint that GitHub rejects. Bounded and expiring —
 * a latency/rate-limit optimization, not a store.
 */
const tokenCache = new Map<string, { token: string; expiresAtMs: number }>()

interface AppIdentity {
    appId: string
    /** Normalized PEM — kept as a string so the fast path never has to parse it. */
    pem: string
    /** Opaque hash of the private key, safe to use in the cache key and to log. */
    keyFingerprint: string
}

/**
 * Read the App id + private key from the agent's secrets WITHOUT parsing the
 * key (cheap enough to run on every call, including cache hits). Refuses a
 * host-bound private-key secret: declaring `GITHUB_APP_PRIVATE_KEY` with
 * `allowed_hosts` would let `@posthog/http-request` substitute the raw signing
 * key into an outbound request, so the safety property the tool relies on is
 * enforced here rather than left to a doc convention.
 */
function resolveAppIdentity(ctx: ToolContext): AppIdentity {
    const appId = ctx.secret(GITHUB_APP_ID_SECRET)
    if (!appId) {
        throw new Error(`github_app_secret_missing: ${GITHUB_APP_ID_SECRET}`)
    }
    if (Array.isArray(ctx.secretAllowedHosts(GITHUB_APP_PRIVATE_KEY_SECRET))) {
        throw new Error(
            `github_app_private_key_host_bound: declare ${GITHUB_APP_PRIVATE_KEY_SECRET} as a bare secret, not with allowed_hosts — a signing key must never be sendable to a host`
        )
    }
    const pem = ctx.secret(GITHUB_APP_PRIVATE_KEY_SECRET)
    if (!pem) {
        throw new Error(`github_app_secret_missing: ${GITHUB_APP_PRIVATE_KEY_SECRET}`)
    }
    // Keys pasted into single-line env forms commonly arrive with literal \n.
    const normalized = pem.includes('\\n') ? pem.split('\\n').join('\n') : pem
    return {
        appId: appId.trim(),
        pem: normalized,
        keyFingerprint: createHash('sha256').update(normalized).digest('hex'),
    }
}

function parsePrivateKey(pem: string): KeyObject {
    try {
        return createPrivateKey(pem)
    } catch {
        // Never echo key material back — not even in the parse error.
        throw new Error(`github_app_invalid_private_key: ${GITHUB_APP_PRIVATE_KEY_SECRET} is not a parseable PEM key`)
    }
}

function base64UrlJson(value: unknown): string {
    return Buffer.from(JSON.stringify(value)).toString('base64url')
}

function mintAppJwt(appId: string, privateKey: KeyObject): string {
    const nowSeconds = Math.floor(Date.now() / 1000)
    const signingInput = `${base64UrlJson({ alg: 'RS256', typ: 'JWT' })}.${base64UrlJson({
        iat: nowSeconds - JWT_CLOCK_DRIFT_SECONDS,
        exp: nowSeconds + JWT_TTL_SECONDS,
        iss: appId,
    })}`
    const signature = createSign('RSA-SHA256').update(signingInput).sign(privateKey, 'base64url')
    return `${signingInput}.${signature}`
}

function appAuthHeaders(jwt: string): Record<string, string> {
    return { Authorization: `Bearer ${jwt}`, Accept: DEFAULT_ACCEPT, 'X-GitHub-Api-Version': API_VERSION }
}

interface RepoRef {
    owner: string
    repo: string
}

/** Parse `/repos/{owner}/{repo}` from a request path; null for non-repo paths. */
function parseRepo(pathname: string): RepoRef | null {
    const m = pathname.match(/^\/repos\/([^/]+)\/([^/]+)/)
    return m ? { owner: m[1], repo: m[2] } : null
}

/** The GitHub account (org or user) a path acts on, for the owner allowlist.
 *  Covers the model-facing surfaces: /repos/{owner}/…, /orgs/{owner}…, /users/{owner}…. */
function parseOwner(pathname: string): string | null {
    const m = pathname.match(/^\/(?:repos|orgs|users)\/([^/]+)/)
    return m ? m[1] : null
}

/**
 * Enforce the optional owner allowlist against the model's requested path.
 * When set, a request must target one of the listed accounts; a path that
 * names no owner is refused too (fail closed — the author opted into a
 * restriction, so an uncheckable request can't slip past it).
 */
function enforceOwnerAllowlist(ctx: ToolContext, pathname: string): void {
    const raw = ctx.secret(GITHUB_APP_ALLOWED_OWNERS_SECRET)
    if (!raw || raw.trim().length === 0) {
        return
    }
    const allowed = new Set(
        raw
            .split(/[,\s]+/)
            .filter(Boolean)
            .map((o) => o.toLowerCase())
    )
    const owner = parseOwner(pathname)
    if (owner === null) {
        throw new Error(
            `github_app_owner_unverifiable: ${GITHUB_APP_ALLOWED_OWNERS_SECRET} is set but this path names no owner to check`
        )
    }
    if (!allowed.has(owner.toLowerCase())) {
        throw new Error(`github_app_owner_not_allowed: ${owner} is not in ${GITHUB_APP_ALLOWED_OWNERS_SECRET}`)
    }
}

/**
 * Resolve which installation to act as: the explicit arg (webhook payloads
 * carry it at `installation.id`), else derived from the repo in the path via
 * the App-JWT lookup endpoint. Non-repo paths can't be derived, so they
 * require the arg.
 */
async function resolveInstallationId(
    ctx: ToolContext,
    jwt: string,
    repo: RepoRef | null,
    explicitId: number | undefined,
    timeoutMs: number
): Promise<number> {
    if (explicitId !== undefined) {
        return explicitId
    }
    if (!repo) {
        throw new Error(
            'github_app_installation_id_required: pass installation_id (webhook payloads carry it at installation.id) for paths outside /repos/{owner}/{repo}'
        )
    }
    const res = await fetchWithTimeout(
        ctx,
        `${API_BASE}/repos/${repo.owner}/${repo.repo}/installation`,
        { method: 'GET', headers: appAuthHeaders(jwt) },
        timeoutMs,
        ERR_PREFIX
    )
    if (!res.ok) {
        throw new Error(`github_app_installation_lookup_failed: ${res.status}`)
    }
    const data = (await res.json()) as { id?: number }
    if (typeof data.id !== 'number') {
        throw new Error('github_app_installation_lookup_failed: response carried no installation id')
    }
    return data.id
}

/** A cached token is usable until it's within the refresh margin of expiry. */
function freshCachedToken(cacheKey: string): string | undefined {
    const cached = tokenCache.get(cacheKey)
    if (cached && cached.expiresAtMs - Date.now() > TOKEN_REFRESH_MARGIN_MS) {
        return cached.token
    }
    return undefined
}

/** Store a minted token. delete-then-set gives LRU insertion order (a refresh
 *  moves the key to the tail), and evicting only after removing the current
 *  key means a refresh at capacity never drops an unrelated live entry. */
function cacheToken(cacheKey: string, token: string, expiresAtMs: number): void {
    tokenCache.delete(cacheKey)
    if (tokenCache.size >= TOKEN_CACHE_MAX_ENTRIES) {
        const oldest = tokenCache.keys().next().value
        if (oldest !== undefined) {
            tokenCache.delete(oldest)
        }
    }
    tokenCache.set(cacheKey, { token, expiresAtMs })
}

async function getInstallationToken(
    ctx: ToolContext,
    installationIdArg: number | undefined,
    repo: RepoRef | null,
    timeoutMs: number
): Promise<string> {
    const identity = resolveAppIdentity(ctx)
    // Down-scope the token to the repo in the path so it only works on the
    // resource being accessed — even a prompt injection that targets an allowed
    // owner can't pivot to other repos in the installation. Non-repo (org-level)
    // paths can't be repo-scoped, so they get a full-installation token.
    const repoScope = repo?.repo
    const scopeKey = repoScope ?? '*'

    // Fast path: an explicit installation id can hit the cache with no crypto
    // and no key parse. The key fingerprint in the cache key is what makes this
    // safe across tenants — see the tokenCache comment.
    if (installationIdArg !== undefined) {
        const hit = freshCachedToken(`${identity.appId}:${installationIdArg}:${identity.keyFingerprint}:${scopeKey}`)
        if (hit) {
            return hit
        }
    }

    const jwt = mintAppJwt(identity.appId, parsePrivateKey(identity.pem))
    const installationId = await resolveInstallationId(ctx, jwt, repo, installationIdArg, timeoutMs)
    const cacheKey = `${identity.appId}:${installationId}:${identity.keyFingerprint}:${scopeKey}`
    // A derived installation id may now hit the cache the explicit fast path couldn't reach.
    const hit = freshCachedToken(cacheKey)
    if (hit) {
        return hit
    }

    const mintHeaders = appAuthHeaders(jwt)
    let mintBody: string | undefined
    if (repoScope) {
        mintHeaders['Content-Type'] = 'application/json'
        // `repositories` names are relative to the installation account, which
        // is this repo's owner (the installation was resolved from it).
        mintBody = JSON.stringify({ repositories: [repoScope] })
    }
    const res = await fetchWithTimeout(
        ctx,
        `${API_BASE}/app/installations/${installationId}/access_tokens`,
        { method: 'POST', headers: mintHeaders, body: mintBody },
        timeoutMs,
        ERR_PREFIX
    )
    if (!res.ok) {
        throw new Error(`github_app_token_mint_failed: ${res.status}`)
    }
    const data = (await res.json()) as { token?: string; expires_at?: string }
    if (typeof data.token !== 'string') {
        throw new Error('github_app_token_mint_failed: response carried no token')
    }
    const expiresAtMs = Date.parse(data.expires_at ?? '')
    if (!Number.isNaN(expiresAtMs)) {
        cacheToken(cacheKey, data.token, expiresAtMs)
    }
    ctx.log('info', 'github_app.token.minted', { installation_id: installationId, repo_scope: repoScope ?? null })
    return data.token
}

/**
 * Join `path` onto the pinned base and re-validate what actually parsed —
 * refuses protocol-relative (`//…`) and absolute-URL smuggling so the minted
 * token can only ever be sent to api.github.com.
 */
function buildApiUrl(path: string): URL {
    if (!path.startsWith('/') || path.startsWith('//')) {
        throw new Error(`github_app_path_invalid: path must start with a single '/' — got ${JSON.stringify(path)}`)
    }
    let url: URL
    try {
        url = new URL(`${API_BASE}${path}`)
    } catch {
        throw new Error(`github_app_path_invalid: ${JSON.stringify(path)} does not form a valid URL`)
    }
    if (url.host !== API_HOST || url.protocol !== 'https:') {
        throw new Error(`github_app_path_invalid: requests are pinned to ${API_BASE}`)
    }
    return url
}

export const githubAppRequestV1 = defineNativeTool({
    id: '@posthog/github-app-request',
    // Same stance as @posthog/http-request: proxy-bound egress pinned to one
    // host, wielding a credential the author explicitly configured — allow.
    approval: 'allow',
    description: [
        'Make an authenticated request to the GitHub REST API (api.github.com only), acting as a GitHub App.',
        'Auth is handled inside the runner: it signs a short-lived App JWT with the GITHUB_APP_PRIVATE_KEY',
        'secret, exchanges it for an installation access token, caches it, and attaches it to the request —',
        'no credential ever appears in the conversation. Requires the GITHUB_APP_ID and',
        'GITHUB_APP_PRIVATE_KEY secrets to be set on the agent. Pass installation_id (found in webhook',
        'payloads at installation.id) when the path is not repo-scoped; repo paths can resolve it themselves.',
        "Set accept to 'application/vnd.github.v3.diff' on a pull request endpoint to fetch the unified diff.",
    ].join(' '),
    args: Type.Object({
        path: Type.String({
            description:
                "GitHub REST API path starting with '/', joined to https://api.github.com. May include a query string, e.g. /repos/PostHog/posthog/pulls/123/files?per_page=100&page=2",
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
        body: Type.Optional(
            Type.Union([Type.String(), Type.Record(Type.String(), Type.Unknown())], {
                description:
                    'Request body. Objects are JSON-encoded with Content-Type application/json; strings are sent verbatim.',
            })
        ),
        accept: Type.Optional(
            Type.String({
                description: `Override the Accept header, e.g. application/vnd.github.v3.diff for a unified diff. Defaults to ${DEFAULT_ACCEPT}.`,
            })
        ),
        installation_id: Type.Optional(
            Type.Integer({
                description:
                    'GitHub App installation id — webhook payloads carry it at installation.id. Optional for /repos/{owner}/{repo}/… paths (resolved via the App), required otherwise.',
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
        /** Selected response headers — includes `link` so the model can paginate. */
        headers: Type.Record(Type.String(), Type.String()),
        truncated: Type.Boolean({ description: 'True if the response body was clipped to max_response_bytes.' }),
    }),
    requires: {},
    cost_hint: 'medium',
    async run(args, ctx) {
        const url = buildApiUrl(args.path)
        enforceOwnerAllowlist(ctx, url.pathname)
        const method = args.method ?? 'GET'
        const timeoutMs = args.timeout_ms ?? DEFAULT_TIMEOUT_MS
        const maxBytes = args.max_response_bytes ?? DEFAULT_MAX_RESPONSE_BYTES

        const token = await getInstallationToken(ctx, args.installation_id, parseRepo(url.pathname), timeoutMs)

        const headers: Record<string, string> = {
            Authorization: `Bearer ${token}`,
            Accept: args.accept ?? DEFAULT_ACCEPT,
            'X-GitHub-Api-Version': API_VERSION,
        }
        // A GET carries no body. Dropping a supplied body silently would let the
        // model believe a mutation ran when it fetched instead — fail loudly so
        // it re-issues with an explicit method.
        if (args.body !== undefined && method === 'GET') {
            throw new Error(
                'github_app_body_with_get: a request body requires an explicit method (POST/PATCH/PUT/DELETE)'
            )
        }
        let body: string | undefined
        if (args.body !== undefined) {
            if (typeof args.body === 'string') {
                body = args.body
            } else {
                body = JSON.stringify(args.body)
                headers['Content-Type'] = 'application/json; charset=utf-8'
            }
        }

        const res = await fetchWithTimeout(ctx, url.toString(), { method, headers, body }, timeoutMs, ERR_PREFIX)
        const { body: bodyOut, bytesRead, truncated } = await readCappedBody(res, maxBytes)
        const headersOut = pickHeaders(res, HEADER_ALLOWLIST)

        ctx.log('info', 'github_app.request.completed', {
            method,
            path: url.pathname,
            status: res.status,
            response_bytes: bytesRead,
            truncated,
        })

        return {
            status: res.status,
            body: bodyOut,
            content_type: res.headers.get('content-type') ?? '',
            headers: headersOut,
            truncated,
        }
    },
})
