/**
 * Trigger-level auth modes: public, pat, posthog_internal, shared_secret.
 *
 * Old equivalent: isolated/auth.test.ts (all 9 cases).
 */

import { createHmac } from 'node:crypto'
import request from 'supertest'

import { sharedSecretVerifier } from '@posthog/agent-ingress'

import { buildCluster, closeSharedPool, Cluster, fakeAuthProvider, fauxText } from '../harness'

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

    describe('shared_secret scheme hmac_sha256 (real verifier)', () => {
        // Runs the REAL sharedSecretVerifier through the real /webhook route so
        // the express `rawBody` capture is on the hook: the signature is over
        // the exact request bytes, which no unit test can prove end to end.
        it('webhook: GitHub-style signature over the raw body → 200; tampered body → 401', async () => {
            const hc = await buildCluster({
                authProvider: {
                    verifiers: [
                        sharedSecretVerifier({
                            resolve: async (ref: string) => (ref === 'GITHUB_WEBHOOK_SECRET' ? 'wh-secret-1' : null),
                        }),
                    ],
                },
            })
            try {
                hc.setScript([fauxText('ack')])
                await hc.deployAgent({
                    slug: 'wh-hmac',
                    spec: {
                        auth: {
                            modes: [
                                {
                                    type: 'shared_secret',
                                    header: 'X-Hub-Signature-256',
                                    secret_ref: 'GITHUB_WEBHOOK_SECRET',
                                    scheme: 'hmac_sha256',
                                },
                            ],
                        },
                    },
                })
                const body = { action: 'review_requested', installation: { id: 42 } }
                const sig = `sha256=${createHmac('sha256', 'wh-secret-1').update(JSON.stringify(body)).digest('hex')}`
                const ok = await request(hc.ingress)
                    .post('/agents/wh-hmac/webhook')
                    .set('X-Hub-Signature-256', sig)
                    .send(body)
                expect(ok.status).toBe(200)
                // Same signature over different bytes — and the raw secret in
                // the header — must both fail.
                const tampered = await request(hc.ingress)
                    .post('/agents/wh-hmac/webhook')
                    .set('X-Hub-Signature-256', sig)
                    .send({ ...body, tampered: true })
                expect(tampered.status).toBe(401)
                const rawSecret = await request(hc.ingress)
                    .post('/agents/wh-hmac/webhook')
                    .set('X-Hub-Signature-256', 'wh-secret-1')
                    .send(body)
                expect(rawSecret.status).toBe(401)
            } finally {
                await hc.teardown()
            }
        })

        it('collapses a replay of the same signed body under a fresh delivery id', async () => {
            // GitHub signs only the body (no timestamp), so a captured signed
            // request could be resent with a new X-GitHub-Delivery to dodge the
            // delivery-id dedup. Keying idempotency on the signature (bound to
            // the body) makes the replay collapse to the original session.
            const hc = await buildCluster({
                authProvider: {
                    verifiers: [
                        sharedSecretVerifier({
                            resolve: async (ref: string) => (ref === 'GITHUB_WEBHOOK_SECRET' ? 'wh-secret-1' : null),
                        }),
                    ],
                },
            })
            try {
                hc.setScript([fauxText('ack'), fauxText('ack')])
                await hc.deployAgent({
                    slug: 'wh-replay',
                    spec: {
                        auth: {
                            modes: [
                                {
                                    type: 'shared_secret',
                                    header: 'X-Hub-Signature-256',
                                    secret_ref: 'GITHUB_WEBHOOK_SECRET',
                                    scheme: 'hmac_sha256',
                                },
                            ],
                        },
                    },
                })
                const body = { action: 'review_requested', installation: { id: 42 } }
                const sig = `sha256=${createHmac('sha256', 'wh-secret-1').update(JSON.stringify(body)).digest('hex')}`
                const first = await request(hc.ingress)
                    .post('/agents/wh-replay/webhook')
                    .set('X-Hub-Signature-256', sig)
                    .set('X-GitHub-Delivery', 'delivery-1')
                    .send(body)
                const replay = await request(hc.ingress)
                    .post('/agents/wh-replay/webhook')
                    .set('X-Hub-Signature-256', sig)
                    .set('X-GitHub-Delivery', 'delivery-2')
                    .send(body)
                expect(first.status).toBe(200)
                expect(replay.status).toBe(200)
                // Same signed body → same session despite the different delivery id.
                expect(replay.body.session_id).toBe(first.body.session_id)
            } finally {
                await hc.teardown()
            }
        })
    })
})
