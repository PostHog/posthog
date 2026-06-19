/**
 * Preview-mode e2e: a session created via the preview ingress path stamps
 * `agent_session.is_preview = true`, every `$ai_*` event the runner emits
 * carries `$agent_is_preview: true`, and the session runs against the DRAFT
 * revision it was addressed to (so per-revision secrets stay isolated from
 * the live revision).
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

describe('preview-mode: real e2e', () => {
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

    it('preview run stamps is_preview on the session row and on every $ai_* event', async () => {
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
        expect(session!.is_preview).toBe(true)
        expect(session!.revision_id).toBe(draft.id)

        // Every emitted analytics event for this session carries the marker.
        // CollectingAnalyticsSink exposes both the raw `AnalyticsEvent` (which
        // we type-stamp with `is_preview`) and the resolved `$ai_*` property
        // bag — assert both so a regression on either side fails the test.
        const entries = c.analytics.forSession(sessionId)
        expect(entries.length).toBeGreaterThan(0)
        for (const e of entries) {
            expect(e.event.is_preview).toBe(true)
            expect(e.properties.$agent_is_preview).toBe(true)
        }
    })

    it('live run leaves is_preview false (regression guard against accidental flag flip)', async () => {
        c.setScript([fauxText('hi from live')])
        await c.deployAgent({ slug: 'preview-live-baseline' })
        const res = await request(c.ingress).post('/agents/preview-live-baseline/run').send({ message: 'hi' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.is_preview).toBe(false)
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
        // Routed to the draft, marked preview — the runner's secret resolver
        // reads the draft revision's `encrypted_env`, so the draft-only
        // `FOO_API_KEY` is what this session ran with.
        expect(session!.is_preview).toBe(true)
        expect(session!.revision_id).toBe(draft.id)
    })

    it('preview run on the same external_key as a live session does not resume the live session', async () => {
        // Regression guard: a preview-authed request must never resume a live
        // session — the runner reads `is_preview` off the session row, so a
        // shared `(application_id, external_key)` would otherwise drag a
        // preview request into a `is_preview = false` row and fire live
        // secrets + un-suppressed external writes. The fix scopes the resume
        // lookup to the preview/live boundary; this case asserts the
        // user-facing outcome (two distinct sessions, each with the right
        // `is_preview` flag).
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

        // Distinct sessions, each correctly flagged.
        expect(previewSessionId).not.toBe(liveSessionId)
        const liveSession = await c.queue.get(liveSessionId)
        const previewSession = await c.queue.get(previewSessionId)
        expect(liveSession!.is_preview).toBe(false)
        expect(previewSession!.is_preview).toBe(true)
        expect(previewSession!.revision_id).toBe(draft.id)
    })

    // Output-adapter and tool-level preview-mode noop branches (slack reply
    // relay, slack-post-message synthetic `ts`, slack-failure-notifier skip,
    // `isPreviewSideEffect` helper) live behind simple session.is_preview
    // checks and are exercised by their own per-service unit tests. An e2e
    // case that wired up a real Slack tool with encrypted bot tokens, mocked
    // the slack.com endpoint, and asserted on the absence of a request would
    // duplicate that coverage without catching any new integration drift —
    // the seam that's hard to keep right under refactor is the flag flowing
    // through the queue + analytics, which the cases above cover.
})
