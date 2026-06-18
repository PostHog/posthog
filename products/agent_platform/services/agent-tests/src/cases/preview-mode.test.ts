/**
 * Preview-mode e2e: a session created via the preview ingress path stamps
 * `agent_session.is_preview = true`, every `$ai_*` event the runner emits
 * carries `$agent_is_preview: true`, and the write-side Slack tool noops
 * its side effect (synthetic `ts` is returned without hitting slack.com).
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
    EncryptedFields,
    INTERNAL_JWT_AUDIENCE,
    mintInternalJwt,
    TEST_S3_BUCKET,
} from '@posthog/agent-shared'

import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

// Mirrors `HARNESS_ENCRYPTION_SALT_KEYS` in cluster.ts — the same value is
// wired into `buildApp({ encryption })`. The override-overlay sub-case
// decrypts the persisted column to assert the round-trip; constructing a
// second `EncryptedFields` here with the same key reads what the ingress
// wrote without reaching into harness internals.
const HARNESS_ENCRYPTION_SALT_KEYS = '01234567890123456789012345678901'

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

    it('preview JWT carrying `sec_ovr` lands an encrypted override on the session row', async () => {
        c.setScript([fauxText('used my override')])
        const { application } = await c.deployAgent({ slug: 'preview-secret-override' })

        // Draft revision declaring a secret name. The override-claim contract
        // is "keys must be a subset of spec.secrets[]" — the JWT path itself
        // doesn't re-validate that on ingress (Django validated at mint), but
        // including the declaration here mirrors how a real author flow would
        // construct the draft they're previewing against.
        const draftSpec = AgentSpecSchema.parse({
            model: 'faux/faux',
            triggers: [
                {
                    type: 'chat',
                    config: {},
                    auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                },
            ],
            secrets: ['FOO_API_KEY'],
        })
        const draft = await c.revisions.createRevision({
            application_id: application.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: `s3://${TEST_S3_BUCKET}/${c.bundlePrefix}/${application.id}/`,
            spec: draftSpec,
        })
        await c.bundle.write(draft.id, 'agent.md', 'You are a secret-override tester.')
        const sha = await c.bundle.freeze(draft.id)
        await c.revisions.setRevisionState(draft.id, 'ready', sha)

        // Mint with the `sec_ovr` claim. Django would emit the same shape
        // after validating keys against `spec.secrets[]`; here we construct
        // it directly so the test exercises the JWT-extraction code path
        // end-to-end without the Django mint hop.
        const token = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.INGRESS_PREVIEW,
            signingKey: DEV_INTERNAL_SIGNING_KEY,
            claims: { app: application.id, rev: draft.id, sec_ovr: { FOO_API_KEY: 'override-from-preview' } },
            ttlSec: 900,
        })

        const slug = `preview-secret-override-${draft.id.replace(/-/g, '')}`
        const res = await request(c.ingress)
            .post(`/agents/${slug}/run`)
            .set('x-agent-preview-token', token)
            .send({ message: 'go' })
        expect(res.status).toBe(200)

        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session).not.toBeNull()
        expect(session!.is_preview).toBe(true)
        // The column is Fernet bytes, not plaintext — assert presence first,
        // then decrypt with a fresh `EncryptedFields` against the same key
        // the ingress wrote with.
        expect(session!.preview_secret_override).not.toBeNull()
        const enc = new EncryptedFields(HARNESS_ENCRYPTION_SALT_KEYS)
        const overlay = enc.decryptJsonEnv(session!.preview_secret_override)
        expect(overlay).toEqual({ FOO_API_KEY: 'override-from-preview' })
    })

    it('preview JWT with no `sec_ovr` leaves the column null (no encrypted-empty-bag rows)', async () => {
        c.setScript([fauxText('no override here')])
        const { application } = await c.deployAgent({ slug: 'preview-no-override' })
        const draftSpec = AgentSpecSchema.parse({
            model: 'faux/faux',
            triggers: [
                {
                    type: 'chat',
                    config: {},
                    auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                },
            ],
        })
        const draft = await c.revisions.createRevision({
            application_id: application.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: `s3://${TEST_S3_BUCKET}/${c.bundlePrefix}/${application.id}/`,
            spec: draftSpec,
        })
        await c.bundle.write(draft.id, 'agent.md', 'You are a preview agent without an override.')
        const sha = await c.bundle.freeze(draft.id)
        await c.revisions.setRevisionState(draft.id, 'ready', sha)

        const token = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.INGRESS_PREVIEW,
            signingKey: DEV_INTERNAL_SIGNING_KEY,
            claims: { app: application.id, rev: draft.id },
            ttlSec: 900,
        })
        const slug = `preview-no-override-${draft.id.replace(/-/g, '')}`
        const res = await request(c.ingress)
            .post(`/agents/${slug}/run`)
            .set('x-agent-preview-token', token)
            .send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.is_preview).toBe(true)
        expect(session!.preview_secret_override).toBeNull()
    })

    // Output-adapter and tool-level preview-mode noop branches (slack reply
    // relay, slack-post-message synthetic `ts`, slack-failure-notifier skip,
    // `isPreviewSideEffect` helper) live behind simple session.is_preview
    // checks and are exercised by their own per-service unit tests. An e2e
    // case that wired up a real Slack tool with encrypted bot tokens, mocked
    // the slack.com endpoint, and asserted on the absence of a request would
    // duplicate that coverage without catching any new integration drift —
    // the seam that's hard to keep right under refactor is the flag flowing
    // through the queue + analytics, which the two cases above cover.

    // Django-side validation of `secret_override` (undeclared key rejection,
    // size cap, live-revision gate) lives in
    // `products/agent_platform/backend/tests/test_preview_token.py` — that
    // tier exercises the body serializer + JWT-claim embedding directly
    // against the Django view, which is more honest than re-faking the
    // mint via supertest here.
})
