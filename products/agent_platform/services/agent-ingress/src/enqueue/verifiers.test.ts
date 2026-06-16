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
        // A valid bearer whose introspect result has no `team` at all.
        // The team-match gate must reject this (no `team` → `undefined !== 7`).
        if (bearer === 'no-team-token') {
            return { uuid: 'u3', email: 'u3@test', team: undefined as unknown as { id: number } }
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

    it.each<[string, Record<string, string>, { status: number; reason?: string }]>([
        ['missing bearer → skip', {}, { status: 0 }],
        ['bad bearer → 401', { authorization: 'Bearer nope' }, { status: 401 }],
        [
            'valid bearer from a different team → 403 wrong_team',
            { authorization: 'Bearer other-team-token' },
            { status: 403, reason: 'wrong_team' },
        ],
        // Defence-in-depth: an introspect response without a `team` must
        // not slip through as a cross-team pass — the gate compares
        // `me.team.id === application.team_id`, which is `undefined !== 7`.
        [
            'valid bearer with no team → 403 wrong_team',
            { authorization: 'Bearer no-team-token' },
            { status: 403, reason: 'wrong_team' },
        ],
    ])('posthog mode: %s', async (_label, headers, expected) => {
        const res = await posthogVerifier(introspector).verify(req(headers), { type: 'posthog', scopes: [] }, APP)
        expect(res).toMatchObject({ ok: false, ...expected })
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

    it('shared_secret: binds x-posthog-caller-id into the principal when sent', async () => {
        const v = sharedSecretVerifier(secretResolver)
        const mode = { type: 'shared_secret' as const, header: 'X-WH', secret_ref: 'WH' }
        const res = await v.verify(req({ 'x-wh': 's3cret', 'x-posthog-caller-id': 'alice' }), mode, APP)
        expect(res.ok).toBe(true)
        if (res.ok) {
            expect(res.principal).toMatchObject({ kind: 'shared_secret', team_id: 7, caller_id: 'alice' })
        }
    })

    it('shared_secret: omits caller_id from the principal when the header is absent', async () => {
        // Single-principal behaviour: callers that don't opt into the
        // per-caller discriminator share one identity (the old behaviour).
        const v = sharedSecretVerifier(secretResolver)
        const mode = { type: 'shared_secret' as const, header: 'X-WH', secret_ref: 'WH' }
        const res = await v.verify(req({ 'x-wh': 's3cret' }), mode, APP)
        expect(res.ok).toBe(true)
        if (res.ok) {
            expect(res.principal).toMatchObject({ kind: 'shared_secret', team_id: 7 })
            expect((res.principal as { caller_id?: string }).caller_id).toBeUndefined()
        }
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
