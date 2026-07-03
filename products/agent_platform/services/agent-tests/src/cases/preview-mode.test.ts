/**
 * Preview-routing e2e: an authed caller can drive a NON-LIVE (draft) revision
 * by addressing the `<slug>-<rev-hex>` URL with a valid `aud=agent-ingress.preview`
 * JWT. A preview run is otherwise indistinguishable from a live run — it
 * executes real tool calls and real side effects, persists real session state,
 * and emits the same analytics — the only difference is which revision handles
 * the request. There is no `is_preview` session marker and no side-effect
 * suppression; this suite guards the routing + revision-scoped resume isolation
 * that make previewing a draft safe to keep.
 *
 * The harness's `deployAgent` always promotes the revision to live, so the
 * test creates a SECOND revision directly via `c.revisions.createRevision`
 * and exercises the `<slug>-<rev-hex>` URL form that the resolver routes to
 * the non-live revision. The preview JWT is minted with the dev signing key
 * the harness wires both sides against.
 */

import request from 'supertest'

import {
    AgentSpecSchema,
    DEV_INTERNAL_SIGNING_KEY,
    INTERNAL_JWT_AUDIENCE,
    mintInternalJwt,
    TEST_S3_BUCKET,
} from '@posthog/agent-shared'

import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

describe('preview-routing: real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster()
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('preview run resolves to and executes against the draft revision', async () => {
        c.setScript([fauxText('hi from draft')])
        // Live revision via the standard harness path — exists so the
        // resolver has a `live_revision_id` to compare against (the
        // preview gate exempts requests resolving to the live id).
        const { application } = await c.deployAgent({ slug: 'preview-basic' })

        // Draft revision attached to the same application — non-live, ready.
        const draftSpec = AgentSpecSchema.parse({
            model: 'faux/faux',
            triggers: [
                { type: 'chat', config: {}, auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] } },
            ],
        })
        const draft = await c.revisions.createRevision({
            application_id: application.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: `s3://${TEST_S3_BUCKET}/${c.bundlePrefix}/${application.id}/`,
            spec: draftSpec,
        })
        await c.bundle.write(draft.id, 'agent.md', 'You are a draft agent.')
        const sha = await c.bundle.freeze(draft.id)
        await c.revisions.setRevisionState(draft.id, 'ready', sha)

        // Preview JWT bound to (application, draft revision).
        const token = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.INGRESS_PREVIEW,
            signingKey: DEV_INTERNAL_SIGNING_KEY,
            claims: { app: application.id, rev: draft.id },
            ttlSec: 900,
        })

        // Hit the `<slug>-<rev-hex>` form so the resolver picks the draft.
        const slug = `preview-basic-${draft.id.replace(/-/g, '')}`
        const res = await request(c.ingress)
            .post(`/agents/${slug}/run`)
            .set('x-agent-preview-token', token)
            .send({ message: 'hi' })
        expect(res.status).toBe(200)
        const sessionId = res.body.session_id as string

        await c.drain()
        const session = await c.queue.get(sessionId)
        expect(session).not.toBeNull()
        // Routed to the draft and ran for real — same analytics a live run emits.
        expect(session!.revision_id).toBe(draft.id)
        const entries = c.analytics.forSession(sessionId)
        expect(entries.length).toBeGreaterThan(0)
    })

    it('preview run resolves to the draft revision carrying its own encrypted_env (per-revision secrets)', async () => {
        c.setScript([fauxText('ran against the draft')])
        const { application } = await c.deployAgent({ slug: 'preview-per-revision-secrets' })

        // Draft revision with its OWN secret block, isolated from whatever the
        // live revision runs with. Secrets live on the revision now, so a
        // preview run against this draft gets exactly these secrets.
        const draftSpec = AgentSpecSchema.parse({
            model: 'faux/faux',
            triggers: [
                { type: 'chat', config: {}, auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] } },
            ],
            secrets: ['FOO_API_KEY'],
        })
        const draft = await c.revisions.createRevision({
            application_id: application.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: `s3://${TEST_S3_BUCKET}/${c.bundlePrefix}/${application.id}/`,
            spec: draftSpec,
            encrypted_env: c.encryption.encrypt(JSON.stringify({ FOO_API_KEY: 'draft-val' })),
        })
        await c.bundle.write(draft.id, 'agent.md', 'You are a draft agent with its own secrets.')
        const sha = await c.bundle.freeze(draft.id)
        await c.revisions.setRevisionState(draft.id, 'ready', sha)

        // Preview JWT bound to (application, draft revision) — no `sec_ovr`.
        const token = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.INGRESS_PREVIEW,
            signingKey: DEV_INTERNAL_SIGNING_KEY,
            claims: { app: application.id, rev: draft.id },
            ttlSec: 900,
        })

        const slug = `preview-per-revision-secrets-${draft.id.replace(/-/g, '')}`
        const res = await request(c.ingress)
            .post(`/agents/${slug}/run`)
            .set('x-agent-preview-token', token)
            .send({ message: 'go' })
        expect(res.status).toBe(200)

        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session).not.toBeNull()
        // Routed to the draft — the runner's secret resolver reads the draft
        // revision's `encrypted_env`, so the draft-only `FOO_API_KEY` is what
        // this session ran with.
        expect(session!.revision_id).toBe(draft.id)
    })

    it('preview run on the same external_key as a live session does not resume the live session', async () => {
        // Regression guard for revision-scoped resume: a preview-authed request
        // routed to a draft must never resume a live session that happens to
        // share an `(application_id, external_key)`. `findByExternalKey` scopes
        // the lookup to `revision_id`, so the draft request opens its own
        // session instead of dragging the author into the live thread. This
        // asserts the user-facing outcome — two distinct sessions, each on the
        // revision the request targeted.
        c.setScript([fauxText('live reply'), fauxText('preview reply')])
        const { application } = await c.deployAgent({ slug: 'preview-iso' })

        // Live session: standard slug, no preview token, an external_key the
        // preview run will collide with.
        const liveRes = await request(c.ingress)
            .post('/agents/preview-iso/run')
            .send({ message: 'live opens thread', external_key: 'shared-thread-key' })
        expect(liveRes.status).toBe(200)
        const liveSessionId = liveRes.body.session_id as string
        await c.drain()

        // Draft revision routed via `<slug>-<rev-hex>`, preview JWT, same key.
        const draftSpec = AgentSpecSchema.parse({
            model: 'faux/faux',
            triggers: [
                { type: 'chat', config: {}, auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] } },
            ],
        })
        const draft = await c.revisions.createRevision({
            application_id: application.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: `s3://${TEST_S3_BUCKET}/${c.bundlePrefix}/${application.id}/`,
            spec: draftSpec,
        })
        await c.bundle.write(draft.id, 'agent.md', 'Draft agent.')
        const sha = await c.bundle.freeze(draft.id)
        await c.revisions.setRevisionState(draft.id, 'ready', sha)
        const token = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.INGRESS_PREVIEW,
            signingKey: DEV_INTERNAL_SIGNING_KEY,
            claims: { app: application.id, rev: draft.id },
            ttlSec: 900,
        })
        const previewSlug = `preview-iso-${draft.id.replace(/-/g, '')}`
        const previewRes = await request(c.ingress)
            .post(`/agents/${previewSlug}/run`)
            .set('x-agent-preview-token', token)
            .send({ message: 'preview author tests', external_key: 'shared-thread-key' })
        expect(previewRes.status).toBe(200)
        const previewSessionId = previewRes.body.session_id as string
        await c.drain()

        // Distinct sessions, each on the revision its request targeted.
        expect(previewSessionId).not.toBe(liveSessionId)
        const liveSession = await c.queue.get(liveSessionId)
        const previewSession = await c.queue.get(previewSessionId)
        expect(liveSession!.revision_id).toBe(application.live_revision_id)
        expect(previewSession!.revision_id).toBe(draft.id)
    })
})
