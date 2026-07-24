/**
 * Guards the bug this whole design closes: an auth mode declared in
 * `AuthModeSchema` but with no verifier wired into the REAL
 * `buildDefaultVerifiers` (so it silently never authenticates in prod). The
 * coverage test below fails the moment a new mode is added without a verifier.
 */

import type { Request } from 'express'
import { createHmac } from 'node:crypto'
import { describe, expect, it } from 'vitest'

import { AgentApplication, AgentRevision, AuthModeSchema } from '@posthog/agent-shared'

import {
    buildDefaultVerifiers,
    posthogInternalVerifier,
    posthogVerifier,
    sharedSecretVerifier,
    type PosthogIdentityIntrospector,
    type TeamOrgLookup,
} from './verifiers'

// Agent owned by team 7, which belongs to org-A.
const APP: AgentApplication = {
    id: 'app-1',
    team_id: 7,
    slug: 'a',
    name: 'A',
    description: '',
    live_revision_id: null,
    archived: false,
}

// The jwt + shared_secret verifiers resolve their secret from the revision's
// `encrypted_env`. The fake `secretResolver` below keys only on the secret
// name, so the env value itself is irrelevant here — but the verifier
// signature requires a revision.
const REV: AgentRevision = {
    id: 'rev-1',
    application_id: APP.id,
    parent_revision_id: null,
    created_by_id: null,
    created_at: 'now',
    state: 'live',
    bundle_uri: 's3://x/',
    bundle_sha256: null,
    spec: { model: 'anthropic/claude-sonnet-4-6' } as unknown as AgentRevision['spec'],
    encrypted_env: null,
}

const introspector: PosthogIdentityIntrospector = {
    async introspect(bearer) {
        // In org-A, can access the agent's team (7).
        if (bearer === 'good-token') {
            return { uuid: 'u1', email: 'u1@test', team: { id: 7 }, organization: { id: 'org-A' } }
        }
        // In org-A, but active project 99 and NO access to team 7 (RBAC).
        if (bearer === 'org-peer-token') {
            return { uuid: 'u2', email: 'u2@test', team: { id: 99 }, organizations: [{ id: 'org-A' }] }
        }
        // A valid user in a different org (org-B).
        if (bearer === 'outsider-token') {
            return { uuid: 'u3', email: 'u3@test', organization: { id: 'org-B' } }
        }
        return null
    },
    // Only `good-token` can reach team 7.
    async canAccessTeam(bearer, teamId) {
        return bearer === 'good-token' && teamId === 7
    },
}

// team 7 → org-A.
const teamOrg: TeamOrgLookup = {
    async orgForTeam(teamId) {
        return teamId === 7 ? 'org-A' : null
    },
}

const PROJECT_MODE = { type: 'posthog' as const, scopes: [], audience: 'project' as const }
const ORG_MODE = { type: 'posthog' as const, scopes: [], audience: 'organization' as const }

const secretResolver = { resolve: async (key: string): Promise<string | null> => (key === 'WH' ? 's3cret' : null) }

const req = (headers: Record<string, string>): Request => ({ headers }) as unknown as Request

/** Request carrying the raw body the express json verify hook captures — the
 *  hmac scheme hashes `rawBodyBytes` (the exact bytes signed). Accepts a Buffer
 *  so tests can exercise non-UTF-8 payloads. */
const signedReq = (headers: Record<string, string>, rawBody: string | Buffer): Request => {
    const bytes = typeof rawBody === 'string' ? Buffer.from(rawBody) : rawBody
    return { headers, rawBody: bytes.toString('utf-8'), rawBodyBytes: bytes } as unknown as Request
}

const allVerifiers = (): ReturnType<typeof buildDefaultVerifiers> =>
    buildDefaultVerifiers({
        introspector,
        teamOrg,
        jwtSecretResolver: secretResolver,
        sharedSecretResolver: secretResolver,
        internalSecret: 'internal-xyz',
    })

describe('buildDefaultVerifiers', () => {
    it('wires a verifier for every declared AuthMode — no mode left unenforced', () => {
        const declared = AuthModeSchema.options.map((o) => o.shape.type.value as string)
        const wired = new Set(allVerifiers().map((v) => v.modeType))
        const missing = declared.filter((m) => !wired.has(m as never))
        expect(missing).toEqual([])
    })

    it('posthog project audience: caller with team access → principal + posthog_api credential', async () => {
        const res = await posthogVerifier(introspector, teamOrg).verify(
            req({ authorization: 'Bearer good-token' }),
            PROJECT_MODE,
            APP,
            REV
        )
        expect(res.ok).toBe(true)
        if (res.ok) {
            expect(res.principal).toMatchObject({ kind: 'posthog', user_id: 'u1', team_id: 7 })
            expect(res.credentials.posthog_api).toEqual({ kind: 'posthog_bearer', token: 'good-token' })
        }
    })

    it('posthog project audience: org peer WITHOUT team access → 403 not_in_project', async () => {
        // Same org as the agent, but no access to the agent's specific team —
        // `project` audience denies them (org membership isn't enough).
        const res = await posthogVerifier(introspector, teamOrg).verify(
            req({ authorization: 'Bearer org-peer-token' }),
            PROJECT_MODE,
            APP,
            REV
        )
        expect(res).toMatchObject({ ok: false, status: 403, reason: 'not_in_project' })
    })

    it('posthog organization audience: any org member passes — even without team access', async () => {
        // The org peer can't reach team 7, but IS in org-A (the agent's org), so
        // `organization` audience admits them. This is the shared-agent case.
        const res = await posthogVerifier(introspector, teamOrg).verify(
            req({ authorization: 'Bearer org-peer-token' }),
            ORG_MODE,
            APP,
            REV
        )
        expect(res.ok).toBe(true)
        if (res.ok) {
            expect(res.principal).toMatchObject({ kind: 'posthog', user_id: 'u2' })
        }
    })

    it('posthog organization audience: a user from a different org → 403 not_in_org', async () => {
        const res = await posthogVerifier(introspector, teamOrg).verify(
            req({ authorization: 'Bearer outsider-token' }),
            ORG_MODE,
            APP,
            REV
        )
        expect(res).toMatchObject({ ok: false, status: 403, reason: 'not_in_org' })
    })

    it.each<[string, Record<string, string>, { status: number; reason?: string }]>([
        ['missing bearer → skip', {}, { status: 0 }],
        ['bad bearer → 401', { authorization: 'Bearer nope' }, { status: 401 }],
    ])('posthog mode: %s', async (_label, headers, expected) => {
        const res = await posthogVerifier(introspector, teamOrg).verify(req(headers), PROJECT_MODE, APP, REV)
        expect(res).toMatchObject({ ok: false, ...expected })
    })

    it('shared_secret: matches resolved encrypted_env secret, 401 on mismatch, 500 when unset', async () => {
        const v = sharedSecretVerifier(secretResolver)
        const mode = { type: 'shared_secret' as const, header: 'X-WH', secret_ref: 'WH' }
        expect(await v.verify(req({ 'x-wh': 's3cret' }), mode, APP, REV)).toMatchObject({ ok: true })
        expect(await v.verify(req({ 'x-wh': 'wrong' }), mode, APP, REV)).toMatchObject({ ok: false, status: 401 })
        expect(await v.verify(req({ 'x-wh': 's3cret' }), { ...mode, secret_ref: 'MISSING' }, APP, REV)).toMatchObject({
            ok: false,
            status: 500,
        })
        expect(await v.verify(req({}), mode, APP, REV)).toMatchObject({ ok: false, status: 0 })
    })

    it('shared_secret hmac_sha256: verifies a GitHub-style signature over the raw body', async () => {
        const v = sharedSecretVerifier(secretResolver)
        const mode = {
            type: 'shared_secret' as const,
            header: 'X-Hub-Signature-256',
            secret_ref: 'WH',
            scheme: 'hmac_sha256' as const,
        }
        const body = '{"action":"review_requested","installation":{"id":42}}'
        const sig = `sha256=${createHmac('sha256', 's3cret').update(body).digest('hex')}`

        const good = await v.verify(signedReq({ 'x-hub-signature-256': sig }, body), mode, APP, REV)
        expect(good).toMatchObject({ ok: true })
        if (good.ok) {
            expect(good.principal).toEqual({ kind: 'shared_secret', team_id: 7 })
        }

        // A signature over different bytes (or with the wrong secret) is a 401 —
        // the raw secret value in the header must NOT pass in this scheme.
        expect(
            await v.verify(signedReq({ 'x-hub-signature-256': sig }, '{"tampered":true}'), mode, APP, REV)
        ).toMatchObject({ ok: false, status: 401 })
        expect(await v.verify(signedReq({ 'x-hub-signature-256': 's3cret' }, body), mode, APP, REV)).toMatchObject({
            ok: false,
            status: 401,
        })
        // No header → skip so the next mode can try; unresolvable secret → fail closed.
        expect(await v.verify(signedReq({}, body), mode, APP, REV)).toMatchObject({ ok: false, status: 0 })
        expect(
            await v.verify(
                signedReq({ 'x-hub-signature-256': sig }, body),
                { ...mode, secret_ref: 'MISSING' },
                APP,
                REV
            )
        ).toMatchObject({ ok: false, status: 500 })
    })

    it('shared_secret hmac_sha256: honors a custom signature_prefix', async () => {
        const v = sharedSecretVerifier(secretResolver)
        const mode = {
            type: 'shared_secret' as const,
            header: 'X-Sig',
            secret_ref: 'WH',
            scheme: 'hmac_sha256' as const,
            signature_prefix: '',
        }
        const body = '{"ping":true}'
        const bare = createHmac('sha256', 's3cret').update(body).digest('hex')
        expect(await v.verify(signedReq({ 'x-sig': bare }, body), mode, APP, REV)).toMatchObject({ ok: true })
        // The GitHub-style default prefix is not accepted once overridden.
        expect(await v.verify(signedReq({ 'x-sig': `sha256=${bare}` }, body), mode, APP, REV)).toMatchObject({
            ok: false,
            status: 401,
        })
    })

    it('shared_secret hmac_sha256: fails loudly (500) when the raw body was never captured', async () => {
        // A route that reached the verifier without the express raw-body hook
        // must not hash '' and 401 every valid signature — that reads as a
        // customer credential problem instead of the server misconfig it is.
        const v = sharedSecretVerifier(secretResolver)
        const mode = {
            type: 'shared_secret' as const,
            header: 'X-Hub-Signature-256',
            secret_ref: 'WH',
            scheme: 'hmac_sha256' as const,
        }
        const noCapture = { headers: { 'x-hub-signature-256': 'sha256=deadbeef' } } as unknown as Request
        expect(await v.verify(noCapture, mode, APP, REV)).toMatchObject({ ok: false, status: 500 })
    })

    it('shared_secret hmac_sha256: hashes the raw bytes, not a UTF-8 re-decode', async () => {
        // A payload with a non-UTF-8 byte (0xff) round-trips losslessly only if
        // we hash the bytes; hashing buf.toString('utf-8') would replace it with
        // U+FFFD and never match the sender's signature.
        const v = sharedSecretVerifier(secretResolver)
        const mode = {
            type: 'shared_secret' as const,
            header: 'X-Hub-Signature-256',
            secret_ref: 'WH',
            scheme: 'hmac_sha256' as const,
        }
        const rawBytes = Buffer.from([0x7b, 0x22, 0x78, 0x22, 0x3a, 0xff, 0x7d]) // {"x":<0xff>}
        const sig = `sha256=${createHmac('sha256', 's3cret').update(rawBytes).digest('hex')}`
        expect(await v.verify(signedReq({ 'x-hub-signature-256': sig }, rawBytes), mode, APP, REV)).toMatchObject({
            ok: true,
        })
    })

    it('shared_secret: yields a single team-scoped principal (no per-caller discriminator)', async () => {
        // One secret == one trust principal. Any holder of the agent's secret
        // is the same principal; per-caller isolation belongs to `jwt`.
        const v = sharedSecretVerifier(secretResolver)
        const mode = { type: 'shared_secret' as const, header: 'X-WH', secret_ref: 'WH' }
        const res = await v.verify(req({ 'x-wh': 's3cret', 'x-posthog-caller-id': 'alice' }), mode, APP, REV)
        expect(res.ok).toBe(true)
        if (res.ok) {
            expect(res.principal).toEqual({ kind: 'shared_secret', team_id: 7 })
        }
    })

    it('posthog_internal: matches the configured secret, 403 on mismatch, 500 when secret empty', async () => {
        const mode = { type: 'posthog_internal' as const }
        expect(
            await posthogInternalVerifier('internal-xyz').verify(
                req({ 'x-posthog-internal': 'internal-xyz' }),
                mode,
                APP,
                REV
            )
        ).toMatchObject({
            ok: true,
        })
        expect(
            await posthogInternalVerifier('internal-xyz').verify(req({ 'x-posthog-internal': 'no' }), mode, APP, REV)
        ).toMatchObject({
            ok: false,
            status: 403,
        })
        expect(
            await posthogInternalVerifier('').verify(req({ 'x-posthog-internal': 'anything' }), mode, APP, REV)
        ).toMatchObject({
            ok: false,
            status: 500,
        })
    })
})
