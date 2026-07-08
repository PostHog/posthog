/**
 * Trigger-level auth modes: public, pat, posthog_internal, shared_secret.
 *
 * Old equivalent: isolated/auth.test.ts (all 9 cases).
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fakeAuthProvider } from '../harness'

const KNOWN_PAT = 'phx_abc123def456'
const KNOWN_INTERNAL_SECRET = 'internal-secret-xyz'
const KNOWN_SHARED_SECRET = 'shared-secret-abc'

const provider = fakeAuthProvider({
    posthog: KNOWN_PAT,
    internal: KNOWN_INTERNAL_SECRET,
    shared: KNOWN_SHARED_SECRET,
})

describe('trigger auth: real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster({ authProvider: provider })
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    describe('public', () => {
        it('enqueues without auth, principal is anonymous', async () => {
            await c.deployAgent({
                slug: 'pub',
                spec: { auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] } },
            })
            const res = await request(c.ingress).post('/agents/pub/run').send({ message: 'x' })
            expect(res.status).toBe(200)
            expect(res.body.principal).toEqual({ kind: 'anonymous' })
        })
    })

    describe('pat', () => {
        it('happy: valid bearer → 200 + service principal', async () => {
            await c.deployAgent({ slug: 'p1', spec: { auth: { modes: [{ type: 'posthog' }] } } })
            const res = await request(c.ingress)
                .post('/agents/p1/run')
                .set('authorization', `Bearer ${KNOWN_PAT}`)
                .send({ message: 'x' })
            expect(res.status).toBe(200)
            expect(res.body.principal.kind).toBe('posthog')
        })

        it('wrong token → 401', async () => {
            await c.deployAgent({ slug: 'p2', spec: { auth: { modes: [{ type: 'posthog' }] } } })
            const res = await request(c.ingress)
                .post('/agents/p2/run')
                .set('authorization', 'Bearer wrong-token')
                .send({ message: 'x' })
            expect(res.status).toBe(401)
        })

        it('missing header → 401', async () => {
            await c.deployAgent({ slug: 'p3', spec: { auth: { modes: [{ type: 'posthog' }] } } })
            const res = await request(c.ingress).post('/agents/p3/run').send({ message: 'x' })
            expect(res.status).toBe(401)
        })
    })

    describe('posthog_internal', () => {
        it('happy: matching internal header → 200 + internal principal', async () => {
            await c.deployAgent({ slug: 'i1', spec: { auth: { modes: [{ type: 'posthog_internal' }] } } })
            const res = await request(c.ingress)
                .post('/agents/i1/run')
                .set('x-posthog-internal', KNOWN_INTERNAL_SECRET)
                .send({ message: 'x' })
            expect(res.status).toBe(200)
            expect(res.body.principal.kind).toBe('posthog_internal')
        })

        it('missing internal header → 401 (no_matching_mode, multi-mode model treats missing creds as 401)', async () => {
            await c.deployAgent({ slug: 'i2', spec: { auth: { modes: [{ type: 'posthog_internal' }] } } })
            const res = await request(c.ingress).post('/agents/i2/run').send({ message: 'x' })
            expect(res.status).toBe(401)
        })

        it('wrong internal header value → 403', async () => {
            await c.deployAgent({ slug: 'i3', spec: { auth: { modes: [{ type: 'posthog_internal' }] } } })
            const res = await request(c.ingress)
                .post('/agents/i3/run')
                .set('x-posthog-internal', 'wrong')
                .send({ message: 'x' })
            expect(res.status).toBe(403)
        })
    })

    describe('shared_secret', () => {
        it('happy: matching header value → 200 + shared_secret principal', async () => {
            await c.deployAgent({
                slug: 's1',
                spec: {
                    auth: { modes: [{ type: 'shared_secret', header: 'x-acme-secret', secret_ref: 'ACME_SECRET' }] },
                },
            })
            const res = await request(c.ingress)
                .post('/agents/s1/run')
                .set('x-acme-secret', KNOWN_SHARED_SECRET)
                .send({ message: 'x' })
            expect(res.status).toBe(200)
            expect(res.body.principal.kind).toBe('shared_secret')
        })

        it('wrong header value → 401', async () => {
            await c.deployAgent({
                slug: 's2',
                spec: {
                    auth: { modes: [{ type: 'shared_secret', header: 'x-acme-secret', secret_ref: 'ACME_SECRET' }] },
                },
            })
            const res = await request(c.ingress)
                .post('/agents/s2/run')
                .set('x-acme-secret', 'wrong')
                .send({ message: 'x' })
            expect(res.status).toBe(401)
        })

        it('missing header → 401', async () => {
            await c.deployAgent({
                slug: 's3',
                spec: {
                    auth: { modes: [{ type: 'shared_secret', header: 'x-acme-secret', secret_ref: 'ACME_SECRET' }] },
                },
            })
            const res = await request(c.ingress).post('/agents/s3/run').send({ message: 'x' })
            expect(res.status).toBe(401)
        })
    })
})
