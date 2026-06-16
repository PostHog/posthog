/**
 * Guards the bug this whole design closes: an auth mode declared in
 * `AuthModeSchema` but with no verifier wired into the REAL
 * `buildDefaultVerifiers` (so it silently never authenticates in prod). The
 * coverage test below fails the moment a new mode is added without a verifier.
 */

import type { Request } from 'express'
import { describe, expect, it } from 'vitest'

import { AgentApplication, AuthModeSchema } from '@posthog/agent-shared'

import {
    buildDefaultVerifiers,
    posthogInternalVerifier,
    posthogVerifier,
    sharedSecretVerifier,
    type PosthogIdentityIntrospector,
} from './verifiers'

const APP: AgentApplication = {
    id: 'app-1',
    team_id: 7,
    slug: 'a',
    name: 'A',
    description: '',
    live_revision_id: null,
    archived: false,
    encrypted_env: null,
}

const introspector: PosthogIdentityIntrospector = {
    async introspect(bearer) {
        if (bearer === 'good-token') {
            return { uuid: 'u1', email: 'u1@test', team: { id: 7 } }
        }
        // A valid bearer whose active team is NOT the agent's owning team (7).
        if (bearer === 'other-team-token') {
            return { uuid: 'u2', email: 'u2@test', team: { id: 99 } }
        }
        return null
    },
}

const secretResolver = { resolve: async (key: string): Promise<string | null> => (key === 'WH' ? 's3cret' : null) }

const req = (headers: Record<string, string>): Request => ({ headers }) as unknown as Request

const allVerifiers = (): ReturnType<typeof buildDefaultVerifiers> =>
    buildDefaultVerifiers({
        introspector,
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

    it('posthog mode: valid bearer → posthog principal + posthog_api credential', async () => {
        const res = await posthogVerifier(introspector).verify(
            req({ authorization: 'Bearer good-token' }),
            { type: 'posthog', scopes: [] },
            APP
        )
        expect(res.ok).toBe(true)
        if (res.ok) {
            expect(res.principal).toMatchObject({ kind: 'posthog', user_id: 'u1', team_id: 7 })
            expect(res.credentials.posthog_api).toEqual({ kind: 'posthog_bearer', token: 'good-token' })
        }
    })

    it('posthog mode: bad bearer → 401, missing bearer → skip', async () => {
        const v = posthogVerifier(introspector)
        expect(
            await v.verify(req({ authorization: 'Bearer nope' }), { type: 'posthog', scopes: [] }, APP)
        ).toMatchObject({
            ok: false,
            status: 401,
        })
        expect(await v.verify(req({}), { type: 'posthog', scopes: [] }, APP)).toMatchObject({ ok: false, status: 0 })
    })

    it('posthog mode: valid bearer from a different team → 403 (no cross-team access)', async () => {
        const res = await posthogVerifier(introspector).verify(
            req({ authorization: 'Bearer other-team-token' }),
            { type: 'posthog', scopes: [] },
            APP
        )
        expect(res).toMatchObject({ ok: false, status: 403, reason: 'wrong_team' })
    })

    it('shared_secret: matches resolved encrypted_env secret, 401 on mismatch, 500 when unset', async () => {
        const v = sharedSecretVerifier(secretResolver)
        const mode = { type: 'shared_secret' as const, header: 'X-WH', secret_ref: 'WH' }
        expect(await v.verify(req({ 'x-wh': 's3cret' }), mode, APP)).toMatchObject({ ok: true })
        expect(await v.verify(req({ 'x-wh': 'wrong' }), mode, APP)).toMatchObject({ ok: false, status: 401 })
        expect(await v.verify(req({ 'x-wh': 's3cret' }), { ...mode, secret_ref: 'MISSING' }, APP)).toMatchObject({
            ok: false,
            status: 500,
        })
        expect(await v.verify(req({}), mode, APP)).toMatchObject({ ok: false, status: 0 })
    })

    it('posthog_internal: matches the configured secret, 403 on mismatch, 500 when secret empty', async () => {
        const mode = { type: 'posthog_internal' as const }
        expect(
            await posthogInternalVerifier('internal-xyz').verify(
                req({ 'x-posthog-internal': 'internal-xyz' }),
                mode,
                APP
            )
        ).toMatchObject({
            ok: true,
        })
        expect(
            await posthogInternalVerifier('internal-xyz').verify(req({ 'x-posthog-internal': 'no' }), mode, APP)
        ).toMatchObject({
            ok: false,
            status: 403,
        })
        expect(
            await posthogInternalVerifier('').verify(req({ 'x-posthog-internal': 'anything' }), mode, APP)
        ).toMatchObject({
            ok: false,
            status: 500,
        })
    })
})
