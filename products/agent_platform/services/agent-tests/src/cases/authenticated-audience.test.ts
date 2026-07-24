/**
 * `authenticated` audience: the posthog auth mode that drops the tenant gate so
 * ANY valid PostHog user may invoke, while still requiring a valid, unrevoked
 * bearer and preserving per-caller identity. Contrasted against `project` (which
 * 403s the same outsider) to prove the audience is the only thing that changed.
 *
 * Real ingress + the real `posthogVerifier`; the introspector is the only fake.
 */

import request from 'supertest'

import {
    AuthProvider,
    posthogVerifier,
    publicVerifier,
    type PosthogIdentityIntrospector,
    type TeamOrgLookup,
} from '@posthog/agent-ingress'

import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

const AGENT_TEAM = 100

// `insider` is in the agent's team+org; `outsider` is a valid PostHog user in a
// DIFFERENT team and org — the one `project`/`organization` audiences reject and
// `authenticated` admits.
const introspector: PosthogIdentityIntrospector = {
    async introspect(bearer: string) {
        if (bearer === 'insider') {
            return { uuid: 'u-insider', email: 'in@test', team: { id: AGENT_TEAM }, organization: { id: 'org-a' } }
        }
        if (bearer === 'outsider') {
            return { uuid: 'u-outsider', email: 'out@test', team: { id: 999 }, organization: { id: 'org-b' } }
        }
        return null
    },
    async canAccessTeam(bearer: string, teamId: number) {
        return bearer === 'insider' && teamId === AGENT_TEAM
    },
}

const teamOrg: TeamOrgLookup = {
    async orgForTeam(teamId: number) {
        return teamId === AGENT_TEAM ? 'org-a' : null
    },
}

const provider: AuthProvider = {
    verifiers: [publicVerifier, posthogVerifier(introspector, teamOrg)],
}

describe('authenticated audience: real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster({ authProvider: provider, teamId: AGENT_TEAM })
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    async function deploy(slug: string, audience: 'project' | 'authenticated'): Promise<void> {
        await c.deployAgent({
            slug,
            teamId: AGENT_TEAM,
            spec: { auth: { modes: [{ type: 'posthog', audience }] } },
        })
    }

    const run = (slug: string, bearer: string): request.Test =>
        request(c.ingress).post(`/agents/${slug}/run`).set('authorization', `Bearer ${bearer}`).send({ message: 'x' })

    it('authenticated: an outsider (different team + org) is admitted → 200, identity preserved', async () => {
        c.setScript([fauxText('ok')])
        await deploy('auth-open', 'authenticated')
        const res = await run('auth-open', 'outsider')
        expect(res.status).toBe(200)
        // Identity survives the dropped tenant gate — this is what keeps
        // per-user session isolation working.
        expect(res.body.principal).toMatchObject({ kind: 'posthog', user_id: 'u-outsider' })
    })

    it('project (contrast): the SAME outsider is rejected → 403 not_in_project', async () => {
        await deploy('proj-closed', 'project')
        const res = await run('proj-closed', 'outsider')
        expect(res.status).toBe(403)
    })

    it('authenticated still fails closed on an invalid/unknown bearer → 401', async () => {
        await deploy('auth-open2', 'authenticated')
        const res = await run('auth-open2', 'nope')
        expect(res.status).toBe(401)
    })
})
