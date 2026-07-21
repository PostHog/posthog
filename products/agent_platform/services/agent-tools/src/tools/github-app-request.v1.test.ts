import { createVerify, generateKeyPairSync } from 'node:crypto'

import type { HttpFetcher } from '@posthog/agent-shared'

import { makeCtx } from '../test-helpers'
import { githubAppRequestV1 } from './github-app-request.v1'

const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
// GitHub ships App keys as PKCS#1 ("BEGIN RSA PRIVATE KEY") PEM.
const PEM = privateKey.export({ type: 'pkcs1', format: 'pem' }) as string
// A second, unrelated key — stands in for an attacker's self-generated PEM.
const OTHER_PEM = generateKeyPairSync('rsa', { modulusLength: 2048 }).privateKey.export({
    type: 'pkcs1',
    format: 'pem',
}) as string

/** Unique app id per test — the tool caches minted tokens per (app, installation). */
let appIdCounter = 9000
function nextAppId(): string {
    return String(appIdCounter++)
}

interface RecordedCall {
    url: string
    init?: RequestInit
}

function fakeResponse(opts: {
    status?: number
    text?: string
    contentType?: string
    headers?: Record<string, string>
}): Response {
    const status = opts.status ?? 200
    const text = opts.text ?? ''
    const headerEntries: Array<[string, string]> = Object.entries(opts.headers ?? {})
    if (opts.contentType !== undefined) {
        headerEntries.push(['content-type', opts.contentType])
    }
    return {
        ok: status >= 200 && status < 300,
        status,
        text: async () => text,
        json: async () => JSON.parse(text),
        headers: {
            get: (k: string) => headerEntries.find(([h]) => h.toLowerCase() === k.toLowerCase())?.[1] ?? null,
            entries: () => headerEntries[Symbol.iterator](),
        },
    } as unknown as Response
}

/**
 * Routed fake of api.github.com: answers the App-auth endpoints (installation
 * lookup, token mint) and returns `apiResponse` for everything else. Records
 * every call so tests can assert which credential went where.
 */
function fakeGithub(opts?: {
    installationId?: number
    tokenExpiresInSeconds?: number
    mintStatus?: number
    apiResponse?: Response
}): { http: HttpFetcher; calls: RecordedCall[]; mintedTokens: string[] } {
    const installationId = opts?.installationId ?? 42
    const calls: RecordedCall[] = []
    const mintedTokens: string[] = []
    const http: HttpFetcher = {
        fetch: async (input, init) => {
            const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : ''
            calls.push({ url, init })
            const mintMatch = url.match(/^https:\/\/api\.github\.com\/app\/installations\/(\d+)\/access_tokens$/)
            if (mintMatch) {
                if (opts?.mintStatus !== undefined && opts.mintStatus >= 400) {
                    return fakeResponse({ status: opts.mintStatus, text: '{"message":"nope"}' })
                }
                const token = `ghs_${mintMatch[1]}_${mintedTokens.length}`
                mintedTokens.push(token)
                const expiresAt = new Date(Date.now() + (opts?.tokenExpiresInSeconds ?? 3600) * 1000).toISOString()
                return fakeResponse({
                    status: 201,
                    text: JSON.stringify({ token, expires_at: expiresAt }),
                    contentType: 'application/json',
                })
            }
            if (/^https:\/\/api\.github\.com\/repos\/[^/]+\/[^/]+\/installation$/.test(url)) {
                return fakeResponse({
                    status: 200,
                    text: JSON.stringify({ id: installationId }),
                    contentType: 'application/json',
                })
            }
            return (
                opts?.apiResponse ?? fakeResponse({ status: 200, text: '{"ok":true}', contentType: 'application/json' })
            )
        },
    }
    return { http, calls, mintedTokens }
}

function makeGithubCtx(
    http: HttpFetcher,
    appId: string,
    pem: string = PEM,
    allowedOwners?: string
): ReturnType<typeof makeCtx> {
    return makeCtx({
        http,
        secret: (name: string) => {
            if (name === 'GITHUB_APP_ID') {
                return appId
            }
            if (name === 'GITHUB_APP_PRIVATE_KEY') {
                return pem
            }
            if (name === 'GITHUB_APP_ALLOWED_OWNERS') {
                return allowedOwners
            }
            return undefined
        },
    })
}

/** Parse the JSON body recorded on a captured mint call (`/access_tokens`). */
function mintBody(calls: RecordedCall[]): unknown {
    const mint = calls.find((c) => c.url.endsWith('/access_tokens'))
    const raw = mint?.init?.body
    return typeof raw === 'string' ? JSON.parse(raw) : raw
}

function bearerOf(call: RecordedCall): string {
    const headers = (call.init?.headers ?? {}) as Record<string, string>
    const auth = Object.entries(headers).find(([k]) => k.toLowerCase() === 'authorization')?.[1] ?? ''
    return auth.replace(/^Bearer /, '')
}

function decodeJwtClaims(jwt: string): Record<string, unknown> {
    const [, payload] = jwt.split('.')
    return JSON.parse(Buffer.from(payload, 'base64url').toString()) as Record<string, unknown>
}

describe('@posthog/github-app-request', () => {
    describe('App auth flow', () => {
        it('mints an installation token with a signed App JWT, then calls the API with the installation token', async () => {
            const appId = nextAppId()
            const { http, calls, mintedTokens } = fakeGithub()
            const out = await githubAppRequestV1.run(
                { path: '/repos/PostHog/posthog/pulls/7/files', installation_id: 42 },
                makeGithubCtx(http, appId)
            )

            const mintCall = calls.find((c) => c.url.endsWith('/access_tokens'))
            expect(mintCall).not.toBeUndefined()
            expect(mintCall?.init?.method).toBe('POST')

            // The mint call authenticates with a valid RS256 App JWT.
            const jwt = bearerOf(mintCall as RecordedCall)
            const [header, payload, signature] = jwt.split('.')
            const verifier = createVerify('RSA-SHA256').update(`${header}.${payload}`)
            expect(verifier.verify(publicKey, signature, 'base64url')).toBe(true)
            expect(JSON.parse(Buffer.from(header, 'base64url').toString())).toEqual({ alg: 'RS256', typ: 'JWT' })
            const claims = decodeJwtClaims(jwt)
            expect(claims.iss).toBe(appId)
            const nowSeconds = Math.floor(Date.now() / 1000)
            expect(claims.iat as number).toBeLessThanOrEqual(nowSeconds)
            // GitHub rejects App JWTs whose exp is more than 10 minutes out.
            expect(claims.exp as number).toBeLessThanOrEqual(nowSeconds + 600)
            expect(claims.exp as number).toBeGreaterThan(nowSeconds)

            // The API call itself carries the installation token, not the JWT.
            const apiCall = calls.find((c) => c.url.includes('/pulls/7/files'))
            expect(apiCall).not.toBeUndefined()
            expect(bearerOf(apiCall as RecordedCall)).toBe(mintedTokens[0])
            const apiHeaders = (apiCall?.init?.headers ?? {}) as Record<string, string>
            expect(apiHeaders['Accept']).toBe('application/vnd.github+json')
            expect(apiHeaders['X-GitHub-Api-Version']).toBe('2022-11-28')

            expect(out.status).toBe(200)
            expect(out.body).toBe('{"ok":true}')
        })

        it('never returns the installation token, JWT, or key material to the model', async () => {
            const appId = nextAppId()
            const { http, mintedTokens } = fakeGithub()
            const out = await githubAppRequestV1.run(
                { path: '/repos/PostHog/posthog/pulls/7', installation_id: 42 },
                makeGithubCtx(http, appId)
            )
            const serialized = JSON.stringify(out)
            expect(serialized).not.toContain(mintedTokens[0])
            expect(serialized).not.toContain('PRIVATE KEY')
            expect(serialized).not.toContain('eyJhbGciOiJSUzI1NiI')
        })

        it('reuses a cached installation token across calls instead of re-minting', async () => {
            const appId = nextAppId()
            const { http, calls } = fakeGithub()
            const ctx = makeGithubCtx(http, appId)
            await githubAppRequestV1.run({ path: '/repos/a/b/issues', installation_id: 42 }, ctx)
            await githubAppRequestV1.run({ path: '/repos/a/b/pulls', installation_id: 42 }, ctx)
            expect(calls.filter((c) => c.url.endsWith('/access_tokens'))).toHaveLength(1)
        })

        it('does not serve a cached token to a caller holding a different private key', async () => {
            // Cross-tenant guard: the cache key binds to a fingerprint of the
            // key, so an agent that declares the victim's public App id +
            // installation id but a different (forged) key gets a cache MISS and
            // mints with its own key — it never rides the victim's token.
            const appId = nextAppId()
            const { http, calls } = fakeGithub()
            await githubAppRequestV1.run(
                { path: '/repos/a/b/issues', installation_id: 42 },
                makeGithubCtx(http, appId, PEM)
            )
            await githubAppRequestV1.run(
                { path: '/repos/a/b/issues', installation_id: 42 },
                makeGithubCtx(http, appId, OTHER_PEM)
            )
            // Two distinct keys → two mints, not a shared cache hit.
            expect(calls.filter((c) => c.url.endsWith('/access_tokens'))).toHaveLength(2)
        })

        it('rejects a host-bound private-key secret (would let http-request exfiltrate the key)', async () => {
            const appId = nextAppId()
            const { http } = fakeGithub()
            const ctx = makeCtx({
                http,
                secret: (name: string) =>
                    name === 'GITHUB_APP_ID' ? appId : name === 'GITHUB_APP_PRIVATE_KEY' ? PEM : undefined,
                secretAllowedHosts: (name: string) =>
                    name === 'GITHUB_APP_PRIVATE_KEY' ? ['api.github.com'] : undefined,
            })
            await expect(
                githubAppRequestV1.run({ path: '/repos/a/b/pulls', installation_id: 42 }, ctx)
            ).rejects.toThrow(/github_app_private_key_host_bound/)
        })

        it('re-mints when the cached token is close to expiry', async () => {
            const appId = nextAppId()
            const { http, calls } = fakeGithub({ tokenExpiresInSeconds: 60 })
            const ctx = makeGithubCtx(http, appId)
            await githubAppRequestV1.run({ path: '/repos/a/b/issues', installation_id: 42 }, ctx)
            await githubAppRequestV1.run({ path: '/repos/a/b/pulls', installation_id: 42 }, ctx)
            expect(calls.filter((c) => c.url.endsWith('/access_tokens'))).toHaveLength(2)
        })

        it('resolves the installation from the repo in the path when installation_id is omitted', async () => {
            const appId = nextAppId()
            const { http, calls, mintedTokens } = fakeGithub({ installationId: 77 })
            const out = await githubAppRequestV1.run(
                { path: '/repos/PostHog/posthog/pulls/7/files' },
                makeGithubCtx(http, appId)
            )
            const lookup = calls.find((c) => c.url.endsWith('/repos/PostHog/posthog/installation'))
            expect(lookup).not.toBeUndefined()
            expect(calls.some((c) => c.url.includes('/app/installations/77/access_tokens'))).toBe(true)
            const apiCall = calls.find((c) => c.url.includes('/pulls/7/files'))
            expect(bearerOf(apiCall as RecordedCall)).toBe(mintedTokens[0])
            expect(out.status).toBe(200)
        })

        it('requires installation_id for paths that are not repo-scoped', async () => {
            const appId = nextAppId()
            const { http } = fakeGithub()
            await expect(
                githubAppRequestV1.run({ path: '/orgs/PostHog/repos' }, makeGithubCtx(http, appId))
            ).rejects.toThrow(/github_app_installation_id_required/)
        })

        it('accepts a private key pasted with literal \\n escapes', async () => {
            const appId = nextAppId()
            const { http } = fakeGithub()
            const escapedPem = PEM.replace(/\n/g, '\\n')
            const out = await githubAppRequestV1.run(
                { path: '/repos/a/b/pulls', installation_id: 42 },
                makeGithubCtx(http, appId, escapedPem)
            )
            expect(out.status).toBe(200)
        })

        it('fails with a clear error when the App secrets are not set', async () => {
            const { http } = fakeGithub()
            await expect(
                githubAppRequestV1.run({ path: '/repos/a/b/pulls', installation_id: 42 }, makeCtx({ http }))
            ).rejects.toThrow(/github_app_secret_missing: GITHUB_APP_ID/)
        })

        it('surfaces the mint failure status when GitHub refuses the token exchange', async () => {
            const appId = nextAppId()
            const { http } = fakeGithub({ mintStatus: 401 })
            await expect(
                githubAppRequestV1.run({ path: '/repos/a/b/pulls', installation_id: 42 }, makeGithubCtx(http, appId))
            ).rejects.toThrow(/github_app_token_mint_failed: 401/)
        })
    })

    describe('blast-radius controls', () => {
        it('down-scopes the minted token to the repo in the path', async () => {
            const appId = nextAppId()
            const { http, calls } = fakeGithub()
            await githubAppRequestV1.run(
                { path: '/repos/PostHog/posthog/pulls/7/files', installation_id: 42 },
                makeGithubCtx(http, appId)
            )
            expect(mintBody(calls)).toEqual({ repositories: ['posthog'] })
        })

        it('mints an unscoped token for a non-repo path (nothing to scope to)', async () => {
            const appId = nextAppId()
            const { http, calls } = fakeGithub()
            await githubAppRequestV1.run(
                { path: '/orgs/PostHog/repos', installation_id: 42 },
                makeGithubCtx(http, appId)
            )
            expect(mintBody(calls)).toBeUndefined()
        })

        it('does not reuse a repo-scoped token for a different repo', async () => {
            // Same install + key, different repo → different scope → separate mint,
            // so the cache never hands repo B's caller a token scoped to repo A.
            const appId = nextAppId()
            const { http, calls } = fakeGithub()
            const ctx = makeGithubCtx(http, appId)
            await githubAppRequestV1.run({ path: '/repos/PostHog/posthog/pulls', installation_id: 42 }, ctx)
            await githubAppRequestV1.run({ path: '/repos/PostHog/other-repo/pulls', installation_id: 42 }, ctx)
            expect(calls.filter((c) => c.url.endsWith('/access_tokens'))).toHaveLength(2)
        })

        it('allows a request whose owner is in GITHUB_APP_ALLOWED_OWNERS', async () => {
            const appId = nextAppId()
            const { http } = fakeGithub()
            const out = await githubAppRequestV1.run(
                { path: '/repos/PostHog/posthog/pulls/7', installation_id: 42 },
                makeGithubCtx(http, appId, PEM, 'PostHog, AnotherOrg')
            )
            expect(out.status).toBe(200)
        })

        it('refuses a request whose owner is not in GITHUB_APP_ALLOWED_OWNERS, before minting', async () => {
            const appId = nextAppId()
            const { http, calls } = fakeGithub()
            await expect(
                githubAppRequestV1.run(
                    { path: '/repos/evil-org/x/pulls/7', installation_id: 99 },
                    makeGithubCtx(http, appId, PEM, 'PostHog')
                )
            ).rejects.toThrow(/github_app_owner_not_allowed/)
            expect(calls).toHaveLength(0)
        })

        it('fails closed when the allowlist is set but the path names no owner', async () => {
            const appId = nextAppId()
            const { http } = fakeGithub()
            await expect(
                githubAppRequestV1.run(
                    { path: '/app/installations', installation_id: 42 },
                    makeGithubCtx(http, appId, PEM, 'PostHog')
                )
            ).rejects.toThrow(/github_app_owner_unverifiable/)
        })
    })

    describe('request dispatch', () => {
        it.each(['//evil.com/pwn', 'https://evil.com/x', 'repos/missing-slash', ''])(
            'refuses a path that does not resolve to api.github.com: %s',
            async (path) => {
                const appId = nextAppId()
                const { http, calls } = fakeGithub()
                await expect(
                    githubAppRequestV1.run({ path, installation_id: 42 }, makeGithubCtx(http, appId))
                ).rejects.toThrow(/github_app_path_invalid/)
                expect(calls).toHaveLength(0)
            }
        )

        it('JSON-encodes an object body and sets Content-Type', async () => {
            const appId = nextAppId()
            const { http, calls } = fakeGithub()
            await githubAppRequestV1.run(
                {
                    path: '/repos/a/b/pulls/7/reviews',
                    method: 'POST',
                    body: { event: 'APPROVE', body: 'lgtm' },
                    installation_id: 42,
                },
                makeGithubCtx(http, appId)
            )
            const apiCall = calls.find((c) => c.url.includes('/reviews'))
            expect(apiCall?.init?.method).toBe('POST')
            expect(apiCall?.init?.body).toBe(JSON.stringify({ event: 'APPROVE', body: 'lgtm' }))
            const headers = (apiCall?.init?.headers ?? {}) as Record<string, string>
            expect(headers['Content-Type']).toContain('application/json')
        })

        it('rejects a body on a default-GET instead of silently dropping it', async () => {
            // The model that passes a body but forgets method must not get a
            // silent GET back — it would think its mutation ran.
            const appId = nextAppId()
            const { http } = fakeGithub()
            await expect(
                githubAppRequestV1.run(
                    { path: '/repos/a/b/issues/1/labels', body: { labels: ['bug'] }, installation_id: 42 },
                    makeGithubCtx(http, appId)
                )
            ).rejects.toThrow(/github_app_body_with_get/)
        })

        it('lets the caller override Accept (e.g. to fetch a PR as a unified diff)', async () => {
            const appId = nextAppId()
            const { http, calls } = fakeGithub({
                apiResponse: fakeResponse({ status: 200, text: 'diff --git a/x b/x', contentType: 'text/plain' }),
            })
            const out = await githubAppRequestV1.run(
                { path: '/repos/a/b/pulls/7', accept: 'application/vnd.github.v3.diff', installation_id: 42 },
                makeGithubCtx(http, appId)
            )
            const apiCall = calls.find((c) => c.url.includes('/pulls/7'))
            const headers = (apiCall?.init?.headers ?? {}) as Record<string, string>
            expect(headers['Accept']).toBe('application/vnd.github.v3.diff')
            expect(out.body).toBe('diff --git a/x b/x')
        })

        it('surfaces the link header so the model can paginate', async () => {
            const appId = nextAppId()
            const link = '<https://api.github.com/repos/a/b/pulls/7/files?page=2>; rel="next"'
            const { http } = fakeGithub({
                apiResponse: fakeResponse({
                    status: 200,
                    text: '[]',
                    contentType: 'application/json',
                    headers: { link },
                }),
            })
            const out = await githubAppRequestV1.run(
                { path: '/repos/a/b/pulls/7/files', installation_id: 42 },
                makeGithubCtx(http, appId)
            )
            expect(out.headers['link']).toBe(link)
        })

        it('truncates responses larger than max_response_bytes', async () => {
            const appId = nextAppId()
            const { http } = fakeGithub({
                apiResponse: fakeResponse({ status: 200, text: 'x'.repeat(500), contentType: 'text/plain' }),
            })
            const out = await githubAppRequestV1.run(
                { path: '/repos/a/b/pulls/7', installation_id: 42, max_response_bytes: 100 },
                makeGithubCtx(http, appId)
            )
            expect(out.truncated).toBe(true)
            expect(out.body).toHaveLength(100)
        })
    })
})
