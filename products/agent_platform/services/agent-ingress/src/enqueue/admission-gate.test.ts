/**
 * `httpTransportClaim` — the chat/HTTP claim builder feeding edge admission.
 * The load-bearing rules:
 *
 *   - The bearer rides on the claim ONLY when it's a credential for the
 *     authoritative provider (posthog bearer ↔ `kind: posthog`). Attaching an
 *     unrelated token trips admission's freshness rule (present-but-invalid
 *     bearer → re-auth, the durable binding is never consulted) and locks out
 *     users who already linked.
 *   - Machine/anonymous principals yield no claim at all: a claim keyed on a
 *     shared principal (e.g. `shared_secret`) would let one secret holder bind
 *     an identity every other holder is then admitted as. The chat trigger
 *     fails closed (403) on a null claim — see `admitChatPrincipal`.
 */

import { describe, expect, it } from 'vitest'

import { AgentSpecSchema, type AgentRevision, type SessionPrincipal } from '@posthog/agent-shared'

import { httpTransportClaim } from './admission-gate'

function revisionWith(spec: Record<string, unknown>): AgentRevision {
    return {
        id: 'rev-1',
        application_id: 'app-1',
        parent_revision_id: null,
        created_by_id: null,
        created_at: new Date(0).toISOString(),
        state: 'live',
        bundle_uri: 's3://x/',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({
            model: 'test/x',
            triggers: [{ type: 'chat', config: {}, auth: { modes: [{ type: 'posthog' }] } }],
            ...spec,
        }),
        encrypted_env: null,
    }
}

const POSTHOG_AUTHORITATIVE = {
    identity_providers: [{ kind: 'posthog', id: 'posthog' }],
    authoritative_provider: 'posthog',
}
const OAUTH2_AUTHORITATIVE = {
    identity_providers: [
        {
            kind: 'oauth2',
            id: 'dogs',
            authorize_url: 'https://idp.test/authorize',
            token_url: 'https://idp.test/token',
            userinfo_url: 'https://idp.test/userinfo',
            client_id: 'c',
        },
    ],
    authoritative_provider: 'dogs',
}

const POSTHOG_PRINCIPAL: SessionPrincipal = {
    kind: 'posthog',
    user_id: 'ph-uuid-1',
    team_id: 1,
    email: 'a@posthog.com',
}
const JWT_PRINCIPAL: SessionPrincipal = { kind: 'jwt', issuer_secret_ref: 'S', sub: 'external-7', claims: {} }

describe('httpTransportClaim', () => {
    it('posthog principal under a posthog authoritative provider attaches the bearer (per-request proof)', () => {
        const claim = httpTransportClaim(POSTHOG_PRINCIPAL, 'phx_tok', revisionWith(POSTHOG_AUTHORITATIVE))
        expect(claim).toMatchObject({ transport: 'posthog', subjectId: 'ph-uuid-1', bearer: { token: 'phx_tok' } })
    })

    it('posthog principal under an oauth2 authoritative provider does NOT attach the bearer (binding path stays reachable)', () => {
        const claim = httpTransportClaim(POSTHOG_PRINCIPAL, 'phx_tok', revisionWith(OAUTH2_AUTHORITATIVE))
        expect(claim).toMatchObject({ transport: 'posthog', subjectId: 'ph-uuid-1' })
        expect(claim?.bearer).toBeUndefined()
    })

    it('jwt claims are issuer-scoped — a colliding sub under another issuer is a different subject — and never attach the JWT as a bearer', () => {
        const claim = httpTransportClaim(JWT_PRINCIPAL, 'a.b.c', revisionWith(OAUTH2_AUTHORITATIVE))
        expect(claim).toMatchObject({ transport: 'jwt', subjectId: 'S:external-7' })
        expect(claim?.bearer).toBeUndefined()
        const otherIssuer = httpTransportClaim(
            { ...JWT_PRINCIPAL, issuer_secret_ref: 'S2' },
            'a.b.c',
            revisionWith(OAUTH2_AUTHORITATIVE)
        )
        expect(otherIssuer?.subjectId).not.toBe(claim?.subjectId)
    })

    it.each<SessionPrincipal>([
        { kind: 'anonymous' },
        { kind: 'shared_secret', team_id: 1 },
        { kind: 'posthog_internal', team_id: 1 },
        { kind: 'service', team_id: 1, id: 'cron' },
    ])('$kind principal yields no claim — no per-sender human identity to admit', (principal) => {
        expect(httpTransportClaim(principal, 'tok', revisionWith(OAUTH2_AUTHORITATIVE))).toBeNull()
    })
})
