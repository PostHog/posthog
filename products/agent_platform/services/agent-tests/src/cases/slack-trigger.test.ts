/**
 * Slack trigger: real Slack event payloads → ingress → enqueue → runner.
 *
 * Old equivalent test surface:
 *   - persistent-chat/slack-thread-continuation.test.ts
 *   - isolated/slack-signature.test.ts
 *   - isolated/slack-identity.test.ts (partial — identity-space is v2 follow-up)
 *
 * Covers:
 *   - url_verification challenge round-trip
 *   - thread_ts dedupe: second mention in same thread resumes
 *   - distinct threads → distinct sessions
 *   - different user in same thread → elevation_required (B.1 v0 security fix
 *     — Slack thread replies must not advance a session opened by another user)
 *   - allow_workspace_participants: owner-only (default) rejects + replies
 *     in-thread; workspace-open lets any trusted-workspace user advance it
 *   - completed thread → fresh session
 *   - bot_id events ignored (no echo loop)
 *   - signature verification: missing, stale, wrong, valid
 */

import { createHmac } from 'crypto'
import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

/** Every signed test below uses the same secret + the matching encrypted_env
 *  entry. Mirrors the real production flow: author sets `SLACK_SIGNING_SECRET`
 *  in their agent's encrypted_env, ingress decrypts at request time, verifies. */
const SLACK_SECRET = 'test-slack-secret'
const SLACK_ENV = { SLACK_SIGNING_SECRET: SLACK_SECRET }

function slackEvent(opts: {
    channel?: string
    user?: string
    text?: string
    ts?: string
    thread_ts?: string
    bot_id?: string
    /** Slack delivers `app_mention` for @-mentions; defaults to `message` for
     *  legacy "any channel message" subscribers. The ingress accepts both. */
    eventType?: 'message' | 'app_mention'
    /** `"im"` (1:1 DM) / `"mpim"` (group DM) / `"channel"` etc. Slack stamps
     *  it on `message` events; the DM gate keys off it. */
    channel_type?: string
    /** Per-event uuid Slack stamps on every callback; identical across
     *  retries of the same event, unique per real event. Used by the ingress
     *  as the idempotency key. Defaults to a value derived from `ts` so each
     *  distinct `ts` is treated as a separate event; tests simulating a retry
     *  pass the same event_id twice with the same ts. */
    event_id?: string
    /** Event-level workspace (Slack sets it on app_mention, omits on message). */
    team?: string
    /** Envelope workspace id; message events rely on this. */
    team_id?: string
}): Record<string, unknown> {
    const ts = opts.ts ?? '1.0'
    return {
        type: 'event_callback',
        event_id: opts.event_id ?? `Ev_test_${ts}`,
        team_id: opts.team_id,
        event: {
            type: opts.eventType ?? 'message',
            channel: opts.channel ?? 'C01',
            channel_type: opts.channel_type,
            team: opts.team,
            user: opts.user ?? 'U01',
            text: opts.text ?? 'hi',
            ts,
            thread_ts: opts.thread_ts,
            bot_id: opts.bot_id,
        },
    }
}

/** Manual signing for the edge-case tests below — `stale timestamp` and
 *  `wrong secret` need control over the inputs that `c.slackPost` packages
 *  up automatically. */
function signSlack(body: string, secret: string, ts: number): { sig: string; tsString: string } {
    const tsString = String(ts)
    const base = `v0:${tsString}:${body}`
    const mac = createHmac('sha256', secret).update(base).digest('hex')
    return { sig: `v0=${mac}`, tsString }
}

describe('slack trigger: real e2e', () => {
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

    it('url_verification challenge round-trips', async () => {
        await c.deployAgent({ slug: 'echo', encrypted_env: SLACK_ENV })
        const res = await c.slackPost('echo', 'events', { type: 'url_verification', challenge: 'xyz' }, SLACK_SECRET)
        expect(res.status).toBe(200)
        expect(res.body.challenge).toBe('xyz')
    })

    it('app_mention event enqueues a session (the primary mention flow)', async () => {
        // The ingress previously only accepted `event.type === 'message'` and
        // silently 200'd app_mention events with no-op. Regression: an
        // app_mention event must enqueue exactly like a channel message.
        c.setScript([fauxText('hello back')])
        await c.deployAgent({ slug: 'mentioner', spec: {}, encrypted_env: SLACK_ENV })
        const res = await c.slackPost(
            'mentioner',
            'events',
            slackEvent({ eventType: 'app_mention', text: '<@U0BOT> ping' }),
            SLACK_SECRET
        )
        expect(res.status).toBe(200)
        expect(res.body.session_id).toBeTruthy()

        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const userMsg = session!.conversation.find((m) => m.role === 'user') as
            | { role: 'user'; content: string }
            | undefined
        // The slack ingress prefixes the seed message with a `[slack]` envelope
        // header so the model can read channel/ts/thread_ts and route replies
        // back to the right thread. The raw user text is at the bottom.
        expect(userMsg?.content).toContain('[slack]')
        expect(userMsg?.content).toContain('channel: C01')
        expect(userMsg?.content).toContain('ts: 1.0')
        expect(userMsg?.content).toContain('<@U0BOT> ping')
    })

    it('seed message includes channel + ts + thread_ts so the model can route replies', async () => {
        // Regression: prior to the slack-envelope embedding fix, the seed
        // message was just `event.text` — the model had no way to know which
        // channel/thread to chat.postMessage back to, so reply tool calls
        // failed at authoring time even for healthy bots.
        c.setScript([fauxText('ok')])
        await c.deployAgent({ slug: 'enveloped', spec: {}, encrypted_env: SLACK_ENV })
        const res = await c.slackPost(
            'enveloped',
            'events',
            slackEvent({
                eventType: 'app_mention',
                channel: 'C-incidents',
                ts: '1700000099.000000',
                thread_ts: '1700000050.000000',
                user: 'U-engineer',
                text: '<@U-bot> any ideas?',
            }),
            SLACK_SECRET
        )
        expect(res.status).toBe(200)
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        const userMsg = session!.conversation.find((m) => m.role === 'user') as
            | { role: 'user'; content: string }
            | undefined
        // Each metadata field on its own line so agent.md can grep-instruct
        // the model and the value substitution is unambiguous.
        expect(userMsg?.content).toMatch(/^\[slack\]$/m)
        expect(userMsg?.content).toMatch(/^channel: C-incidents$/m)
        expect(userMsg?.content).toMatch(/^ts: 1700000099\.000000$/m)
        expect(userMsg?.content).toMatch(/^thread_ts: 1700000050\.000000$/m)
        expect(userMsg?.content).toMatch(/^user: U-engineer$/m)
        // Raw text follows the header block.
        expect(userMsg?.content).toContain('<@U-bot> any ideas?')
    })

    it('Slack retry with the same event_id is idempotent — does not double-reply', async () => {
        // Slack retries the events callback up to 3 times if it doesn't see a
        // 200 within 3 seconds. Pre-fix, the externalKey-based resume path
        // would append a duplicate seed to pending_inputs on each retry and
        // the runner would reply N times to the same mention. Using the
        // top-level `event_id` as the idempotency key short-circuits retries
        // before they touch pending_inputs.
        c.setScript([fauxText('once and only once')])
        await c.deployAgent({ slug: 'no-dupes', spec: {}, encrypted_env: SLACK_ENV })
        const payload = slackEvent({
            eventType: 'app_mention',
            event_id: 'Ev_retry_canary',
            text: '<@U-bot> say hi',
        })
        const first = await c.slackPost('no-dupes', 'events', payload, SLACK_SECRET)
        expect(first.status).toBe(200)
        // Same payload — simulates Slack's retry. Should resolve to the same
        // session, NOT append to pending_inputs.
        const retry = await c.slackPost('no-dupes', 'events', payload, SLACK_SECRET)
        expect(retry.status).toBe(200)
        expect(retry.body.session_id).toBe(first.body.session_id)

        await c.drain()
        const session = await c.queue.get(first.body.session_id)
        const userMsgs = session!.conversation.filter((m) => m.role === 'user')
        // Exactly one user turn — retry was deduped.
        expect(userMsgs).toHaveLength(1)
        // And no leftover pending_inputs that would have caused a second turn.
        expect(session!.pending_inputs).toHaveLength(0)
        // Assistant should have replied exactly once.
        const assistantTexts = session!.conversation.filter((m) => m.role === 'assistant')
        expect(assistantTexts).toHaveLength(1)
    })

    it('app_mention + message.channels for one mention dedupe to a single turn', async () => {
        // Slack fires both events for an @-mention: same ts, distinct event_id.
        c.setScript([fauxText('once')])
        await c.deployAgent({ slug: 'no-double', spec: {}, encrypted_env: SLACK_ENV })
        const ts = '1700000200.000100'
        const mention = await c.slackPost(
            'no-double',
            'events',
            slackEvent({ eventType: 'app_mention', ts, event_id: 'Ev_mention', text: '<@U-bot> hi' }),
            SLACK_SECRET
        )
        const message = await c.slackPost(
            'no-double',
            'events',
            slackEvent({ eventType: 'message', ts, event_id: 'Ev_message', text: '<@U-bot> hi' }),
            SLACK_SECRET
        )
        expect(mention.status).toBe(200)
        expect(message.status).toBe(200)
        expect(message.body.session_id).toBe(mention.body.session_id)

        await c.drain()
        const session = await c.queue.get(mention.body.session_id)
        expect(session!.conversation.filter((m) => m.role === 'user')).toHaveLength(1)
        expect(session!.pending_inputs).toHaveLength(0)
        expect(session!.conversation.filter((m) => m.role === 'assistant')).toHaveLength(1)
    })

    it('message event without event.team gates trust on the envelope team_id', async () => {
        c.setScript([fauxText('ok')])
        await c.deployAgent({
            slug: 'ws-fallback',
            spec: { triggers: [{ type: 'slack', config: { trusted_workspaces: ['T-TRUSTED'] } }] },
            encrypted_env: SLACK_ENV,
        })
        // message events omit event.team — the envelope team_id must still gate.
        const ok = await c.slackPost(
            'ws-fallback',
            'events',
            slackEvent({ eventType: 'message', ts: '1.0', team_id: 'T-TRUSTED', text: 'hello' }),
            SLACK_SECRET
        )
        expect(ok.status).toBe(200)
        expect(ok.body.session_id).toBeTruthy()
        // An untrusted envelope is dropped, not enqueued — but acked 200 with a
        // drop indication, never a 4xx: a signed delivery that fails the workspace
        // allowlist is a routing decision, and providers retry non-2xx (Slack
        // redelivery storms). The drop is what matters; the status is 2xx.
        const dropped = await c.slackPost(
            'ws-fallback',
            'events',
            slackEvent({ eventType: 'message', ts: '2.0', team_id: 'T-OTHER', text: 'hello' }),
            SLACK_SECRET
        )
        expect(dropped.status).toBe(200)
        expect(dropped.body.dropped).toBe('workspace_not_trusted')
        expect(dropped.body.session_id).toBeFalsy()
    })

    it('thread_ts falls back to ts when the mention is a top-level channel message', async () => {
        // Slack omits thread_ts for top-level messages. A reply still needs a
        // value (otherwise chat.postMessage would post to channel root, not
        // threaded), so the seed substitutes ts → thread_ts in that case.
        c.setScript([fauxText('ok')])
        await c.deployAgent({ slug: 'top-level', spec: {}, encrypted_env: SLACK_ENV })
        const res = await c.slackPost(
            'top-level',
            'events',
            slackEvent({ eventType: 'app_mention', ts: '99.000', thread_ts: undefined }),
            SLACK_SECRET
        )
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        const userMsg = session!.conversation.find((m) => m.role === 'user') as
            | { role: 'user'; content: string }
            | undefined
        expect(userMsg?.content).toMatch(/^ts: 99\.000$/m)
        expect(userMsg?.content).toMatch(/^thread_ts: 99\.000$/m)
    })

    it('thread_ts dedupe: second mention in same thread resumes existing session', async () => {
        c.setScript([fauxText('first reply'), fauxText('second reply')])
        await c.deployAgent({ slug: 'thready', spec: {}, encrypted_env: SLACK_ENV })
        const first = await c.slackPost(
            'thready',
            'events',
            slackEvent({ ts: '1', thread_ts: '1', text: 'first' }),
            SLACK_SECRET
        )
        expect(first.body.resumed).toBe(false)

        const second = await c.slackPost(
            'thready',
            'events',
            slackEvent({ ts: '2', thread_ts: '1', text: 'second' }),
            SLACK_SECRET
        )
        expect(second.body.resumed).toBe(true)
        expect(second.body.session_id).toBe(first.body.session_id)

        await c.drain()
        const session = await c.queue.get(first.body.session_id)
        // First message in conversation, second was queued into pending_inputs
        // and then drained by the next turn.
        const userMsgs = session!.conversation.filter((m) => m.role === 'user')
        expect(userMsgs.length).toBe(2)
        // Per-message sender stamping (#23 step 1): every user turn carries
        // the principal who sent it. Both messages here came from U01.
        for (const msg of userMsgs) {
            if (msg.role === 'user' && msg.sender?.kind === 'slack') {
                expect(msg.sender.slack_user_id).toBeTruthy()
            } else if (msg.role === 'user') {
                throw new Error('expected slack sender')
            }
        }
        const ids = userMsgs
            .filter((m) => m.role === 'user')
            .map((m) => (m.role === 'user' && m.sender?.kind === 'slack' ? m.sender.slack_user_id : null))
        expect(new Set(ids).size).toBe(1)
    })

    it('multi-user thread (post-elevation): each turn carries the sender that produced it', async () => {
        // Builds on the B.1 ACL fix: bob's message is denied until alice
        // grants. After the grant, bob's replayed message lands in
        // pending_inputs with sender=bob. Asserts the per-message stamping
        // contract that #23 step 3 (dispatcher per-asker auth) will rely on.
        c.setScript([fauxText('first reply'), fauxText('after grant')])
        await c.deployAgent({ slug: 'multiuser', spec: {}, encrypted_env: SLACK_ENV })

        // Alice opens the thread.
        const opened = await c.slackPost(
            'multiuser',
            'events',
            slackEvent({ user: 'U-ALICE', ts: '1', thread_ts: '1', text: 'alice opens' }),
            SLACK_SECRET
        )
        await c.drain()

        // Bob tries to reply — rejected.
        const bob = await c.slackPost(
            'multiuser',
            'events',
            slackEvent({ user: 'U-BOB', ts: '2', thread_ts: '1', text: 'bob barges in' }),
            SLACK_SECRET
        )
        expect(bob.body.elevation_required).toBe(true)

        // Alice grants via interactivity.
        const grant = await c.slackPost(
            'multiuser',
            'interactivity',
            {
                payload: JSON.stringify({
                    type: 'block_actions',
                    team: { id: 'unknown' },
                    user: { id: 'U-ALICE' },
                    actions: [
                        {
                            action_id: 'elevation_decision',
                            value: `elevation:grant:${opened.body.session_id}:${bob.body.elevation_request_id}`,
                        },
                    ],
                }),
            },
            SLACK_SECRET
        )
        expect(grant.status).toBe(200)
        await c.drain()

        const session = (await c.queue.get(opened.body.session_id))!
        const userMsgs = session.conversation.filter((m) => m.role === 'user')
        // Alice's opening + Bob's replayed reply.
        expect(userMsgs.length).toBe(2)
        const slackUserIds = userMsgs.map((m) =>
            m.role === 'user' && m.sender?.kind === 'slack' ? m.sender.slack_user_id : null
        )
        // Distinct senders by Slack user id — exactly what #23 step 3
        // needs to read at dispatch time to authorise per-asker.
        expect(new Set(slackUserIds).size).toBe(2)

        // The slack handler also stamps `agent_user_id` (the identity-store
        // uuid) on the principal so the dispatcher has a stable handle for
        // the #23 step 2 bridge. Resolve each via the identity store and
        // verify the underlying slack principals are really alice + bob.
        const agentUserIds = userMsgs.map((m) =>
            m.role === 'user' && m.sender?.kind === 'slack' ? m.sender.agent_user_id : null
        )
        const resolved: string[] = []
        for (const id of agentUserIds) {
            expect(typeof id).toBe('string')
            const agentUser = await c.identities.getById(id as string)
            expect(agentUser).not.toBeNull()
            resolved.push(agentUser!.principal_id)
        }
        expect(resolved.sort()).toEqual(['unknown:U-ALICE', 'unknown:U-BOB'])
    })

    it('different user in same thread → elevation_required, session is NOT advanced', async () => {
        // The Slack security gap (B.1 v0): before this fix, any Slack user
        // who could post in a thread could resume someone else's session by
        // virtue of thread_ts/externalKey matching. Now the second user's
        // message is rejected, recorded as a PendingElevationRequest, and
        // the session stays parked until the owner grants elevation.
        c.setScript([fauxText('first reply')])
        await c.deployAgent({ slug: 'gated', spec: {}, encrypted_env: SLACK_ENV })
        const first = await c.slackPost(
            'gated',
            'events',
            slackEvent({ user: 'U-ALICE', ts: '1', thread_ts: '1', text: 'alice opens' }),
            SLACK_SECRET
        )
        expect(first.body.resumed).toBe(false)
        await c.drain()

        const second = await c.slackPost(
            'gated',
            'events',
            slackEvent({ user: 'U-BOB', ts: '2', thread_ts: '1', text: 'bob barges in' }),
            SLACK_SECRET
        )
        // Slack expects 200 on events; the elevation is signalled in the body.
        expect(second.status).toBe(200)
        expect(second.body.elevation_required).toBe(true)
        expect(second.body.session_id).toBe(first.body.session_id)
        expect(second.body.resumed).toBe(false)
        expect(second.body.elevation_request_id).toMatch(/.+/)

        const session = await c.queue.get(first.body.session_id)
        // Bob's message must NOT be visible to the runner.
        expect(session!.pending_inputs).toHaveLength(0)
        const userMsgs = session!.conversation.filter((m) => m.role === 'user')
        // The seed now carries a `[slack]` envelope header; the raw text
        // is at the bottom. Assert against the raw line rather than the
        // full content so the slack-metadata format can evolve without
        // touching unrelated identity / elevation tests.
        expect(userMsgs.map((m) => m.content)).toHaveLength(1)
        expect(userMsgs[0].content).toContain('alice opens')
        // It IS preserved on the elevation request so a future grant can replay.
        expect(session!.pending_elevation_requests).toHaveLength(1)
        expect(session!.pending_elevation_requests[0].state).toBe('pending')
        expect(session!.pending_elevation_requests[0].trigger).toBe('slack')
    })

    describe('slack interactivity: elevation grant / decline', () => {
        // The button `value` shape the ingress encodes/decodes — keep in sync
        // with `encodeElevationActionValue` in services/agent-ingress/src/triggers/slack.ts.
        function buildPayload(opts: {
            sessionId: string
            requestId: string
            decision: 'grant' | 'decline'
            user: string
            workspaceId?: string
        }): string {
            return JSON.stringify({
                type: 'block_actions',
                team: { id: opts.workspaceId ?? 'unknown' },
                user: { id: opts.user },
                actions: [
                    {
                        action_id: 'elevation_decision',
                        value: `elevation:${opts.decision}:${opts.sessionId}:${opts.requestId}`,
                    },
                ],
            })
        }

        async function setupRejectedRequest(slug: string): Promise<{ sessionId: string; requestId: string }> {
            c.setScript([fauxText('first reply'), fauxText('after grant')])
            await c.deployAgent({ slug, spec: {}, encrypted_env: SLACK_ENV })
            const first = await c.slackPost(
                slug,
                'events',
                slackEvent({ user: 'U-ALICE', ts: '1', thread_ts: '1', text: 'alice opens' }),
                SLACK_SECRET
            )
            await c.drain()
            const bob = await c.slackPost(
                slug,
                'events',
                slackEvent({ user: 'U-BOB', ts: '2', thread_ts: '1', text: 'bob barges in' }),
                SLACK_SECRET
            )
            return { sessionId: first.body.session_id, requestId: bob.body.elevation_request_id }
        }

        it('owner grant: ACL entry written, bob message replays, session re-queues', async () => {
            const { sessionId, requestId } = await setupRejectedRequest('gated-grant')

            const grant = await c.slackPost(
                'gated-grant',
                'interactivity',
                {
                    payload: buildPayload({
                        sessionId,
                        requestId,
                        decision: 'grant',
                        user: 'U-ALICE',
                    }),
                },
                SLACK_SECRET
            )
            expect(grant.status).toBe(200)
            expect(grant.body.text).toMatch(/granted/i)

            // Drain a turn so the runner picks up bob's now-replayed message.
            await c.drain()
            const session = await c.queue.get(sessionId)
            expect(session!.acl).toHaveLength(1)
            expect(session!.acl[0].state).toBe('active')
            expect(session!.pending_elevation_requests[0].state).toBe('granted')
            // Conversation now reflects bob's message being delivered.
            // Each turn is wrapped in a `[slack]` envelope header; assert
            // on the raw text inside rather than the exact full content.
            const userMsgs = session!.conversation.filter((m) => m.role === 'user')
            expect(userMsgs).toHaveLength(2)
            expect(userMsgs[0].content).toContain('alice opens')
            expect(userMsgs[1].content).toContain('bob barges in')
        })

        it('non-owner click: ephemeral message, request stays pending', async () => {
            const { sessionId, requestId } = await setupRejectedRequest('gated-noowner')

            const stranger = await c.slackPost(
                'gated-noowner',
                'interactivity',
                {
                    payload: buildPayload({
                        sessionId,
                        requestId,
                        decision: 'grant',
                        user: 'U-CAROL',
                    }),
                },
                SLACK_SECRET
            )
            expect(stranger.status).toBe(200)
            expect(stranger.body.response_type).toBe('ephemeral')
            expect(stranger.body.text).toMatch(/only the session owner/i)

            const session = await c.queue.get(sessionId)
            expect(session!.acl).toHaveLength(0)
            expect(session!.pending_elevation_requests[0].state).toBe('pending')
        })

        it('decline: marks request declined, does not advance the session', async () => {
            const { sessionId, requestId } = await setupRejectedRequest('gated-decline')

            const decline = await c.slackPost(
                'gated-decline',
                'interactivity',
                {
                    payload: buildPayload({
                        sessionId,
                        requestId,
                        decision: 'decline',
                        user: 'U-ALICE',
                    }),
                },
                SLACK_SECRET
            )
            expect(decline.status).toBe(200)
            expect(decline.body.text).toMatch(/declined/i)

            const session = await c.queue.get(sessionId)
            expect(session!.acl).toHaveLength(0)
            expect(session!.pending_inputs).toHaveLength(0)
            expect(session!.pending_elevation_requests[0].state).toBe('declined')
        })

        it('replaying a grant on an already-decided request returns "already decided"', async () => {
            const { sessionId, requestId } = await setupRejectedRequest('gated-replay')

            const first = await c.slackPost(
                'gated-replay',
                'interactivity',
                {
                    payload: buildPayload({
                        sessionId,
                        requestId,
                        decision: 'grant',
                        user: 'U-ALICE',
                    }),
                },
                SLACK_SECRET
            )
            expect(first.status).toBe(200)
            await c.drain()

            const second = await c.slackPost(
                'gated-replay',
                'interactivity',
                {
                    payload: buildPayload({
                        sessionId,
                        requestId,
                        decision: 'grant',
                        user: 'U-ALICE',
                    }),
                },
                SLACK_SECRET
            )
            expect(second.status).toBe(200)
            expect(second.body.response_type).toBe('ephemeral')
            expect(second.body.text).toMatch(/already been decided/i)
        })

        it('missing payload returns 400', async () => {
            await c.deployAgent({ slug: 'gated-bad', spec: {}, encrypted_env: SLACK_ENV })
            const res = await c.slackPost('gated-bad', 'interactivity', {}, SLACK_SECRET)
            expect(res.status).toBe(400)
            expect(res.body.error).toBe('missing_payload')
        })

        it('unknown session id returns 404', async () => {
            await c.deployAgent({ slug: 'gated-missing', spec: {}, encrypted_env: SLACK_ENV })
            const res = await c.slackPost(
                'gated-missing',
                'interactivity',
                {
                    payload: buildPayload({
                        sessionId: '00000000-0000-0000-0000-000000000000',
                        requestId: 'fake',
                        decision: 'grant',
                        user: 'U-ALICE',
                    }),
                },
                SLACK_SECRET
            )
            expect(res.status).toBe(404)
            expect(res.body.error).toBe('session_not_found')
        })
    })

    it('distinct threads create distinct sessions', async () => {
        await c.deployAgent({ slug: 'distinct', spec: {}, encrypted_env: SLACK_ENV })
        const a = await c.slackPost(
            'distinct',
            'events',
            slackEvent({ ts: '1', thread_ts: '1', text: 'thread a' }),
            SLACK_SECRET
        )
        const b = await c.slackPost(
            'distinct',
            'events',
            slackEvent({ ts: '2', thread_ts: '2', text: 'thread b' }),
            SLACK_SECRET
        )
        expect(a.body.session_id).not.toBe(b.body.session_id)
    })

    it('bot_id events are ignored (no echo loop)', async () => {
        await c.deployAgent({ slug: 'noloop', encrypted_env: SLACK_ENV })
        const res = await c.slackPost(
            'noloop',
            'events',
            slackEvent({ bot_id: 'B01', text: 'I am a bot' }),
            SLACK_SECRET
        )
        expect(res.status).toBe(200)
        expect(res.body.session_id).toBeUndefined()
    })

    it('idle `completed` (open) thread is resumed on the next mention', async () => {
        // Under the new state machine `completed` is open by default —
        // external_key reuse picks it back up. Only `closed` (via
        // meta-end-session) or `failed` forces a fresh session.
        c.setScript([fauxText('done'), fauxText('again')])
        await c.deployAgent({ slug: 'freshish', spec: {}, encrypted_env: SLACK_ENV })
        const first = await c.slackPost(
            'freshish',
            'events',
            slackEvent({ ts: '1', thread_ts: '1', text: 'first' }),
            SLACK_SECRET
        )
        await c.drain()
        expect((await c.queue.get(first.body.session_id))!.state).toBe('completed')

        const second = await c.slackPost(
            'freshish',
            'events',
            slackEvent({ ts: '2', thread_ts: '1', text: 'second' }),
            SLACK_SECRET
        )
        // Same external_key, session is open → resumed.
        expect(second.body.resumed).toBe(true)
        expect(second.body.session_id).toBe(first.body.session_id)
    })

    it('`closed` thread starts a fresh session on the next mention', async () => {
        c.setScript([fauxCallTool('@posthog/meta-end-session', { summary: 'done' }), fauxText('again')])
        await c.deployAgent({ slug: 'freshish-closed', spec: {}, encrypted_env: SLACK_ENV })
        const first = await c.slackPost(
            'freshish-closed',
            'events',
            slackEvent({ ts: '1', thread_ts: '1', text: 'first' }),
            SLACK_SECRET
        )
        await c.drain()
        expect((await c.queue.get(first.body.session_id))!.state).toBe('closed')

        const second = await c.slackPost(
            'freshish-closed',
            'events',
            slackEvent({ ts: '2', thread_ts: '1', text: 'second' }),
            SLACK_SECRET
        )
        // Closed session is terminal → fresh session.
        expect(second.body.resumed).toBe(false)
        expect(second.body.session_id).not.toBe(first.body.session_id)
    })

    describe('signature verification', () => {
        const secret = SLACK_SECRET

        async function withSigCluster(): Promise<Cluster> {
            const cluster = await buildCluster()
            // Real flow: signing secret lives in the agent's encrypted_env;
            // the ingress's resolver decrypts at request time.
            await cluster.deployAgent({ slug: 'signed', encrypted_env: SLACK_ENV })
            return cluster
        }

        it('missing signature → 401', async () => {
            const cc = await withSigCluster()
            try {
                const res = await request(cc.ingress)
                    .post('/agents/signed/slack/events')
                    .set('x-slack-request-timestamp', String(Math.floor(Date.now() / 1000)))
                    .send(slackEvent({}))
                expect(res.status).toBe(401)
            } finally {
                await cc.teardown()
            }
        })

        it('stale timestamp (>5 min) → 401 (replay protection)', async () => {
            const cc = await withSigCluster()
            try {
                const stale = Math.floor(Date.now() / 1000) - 10 * 60
                const body = JSON.stringify(slackEvent({}))
                const { sig } = signSlack(body, secret, stale)
                const res = await request(cc.ingress)
                    .post('/agents/signed/slack/events')
                    .set('content-type', 'application/json')
                    .set('x-slack-request-timestamp', String(stale))
                    .set('x-slack-signature', sig)
                    .send(body)
                expect(res.status).toBe(401)
            } finally {
                await cc.teardown()
            }
        })

        it('signature signed with wrong secret → 401', async () => {
            const cc = await withSigCluster()
            try {
                const now = Math.floor(Date.now() / 1000)
                const body = JSON.stringify(slackEvent({}))
                const { sig } = signSlack(body, 'wrong-secret', now)
                const res = await request(cc.ingress)
                    .post('/agents/signed/slack/events')
                    .set('content-type', 'application/json')
                    .set('x-slack-request-timestamp', String(now))
                    .set('x-slack-signature', sig)
                    .send(body)
                expect(res.status).toBe(401)
            } finally {
                await cc.teardown()
            }
        })

        it('valid signature → 200', async () => {
            const cc = await withSigCluster()
            try {
                const res = await cc.slackPost(
                    'signed',
                    'events',
                    { type: 'url_verification', challenge: 'xyz' },
                    SLACK_SECRET
                )
                expect(res.status).toBe(200)
                expect(res.body.challenge).toBe('xyz')
            } finally {
                await cc.teardown()
            }
        })
    })

    describe('mention_only + auto_resume_threads', () => {
        /** Slack trigger configured to require @-mentions to start a session,
         *  optionally letting non-mention replies through when they land in a
         *  thread the bot already owns. */
        function trigger(opts: { mention_only: boolean; auto_resume_threads: boolean }): Record<string, unknown> {
            return {
                type: 'slack',
                config: {
                    mention_only: opts.mention_only,
                    auto_resume_threads: opts.auto_resume_threads,
                    trusted_workspaces: '*',
                },
            }
        }

        it('mention_only=false (default): plain message events still enqueue (back-compat)', async () => {
            // The original behaviour was "accept anything that isn't a bot
            // message" — keep that working unchanged when mention_only is off,
            // so existing bots that watch whole channels don't regress.
            c.setScript([fauxText('saw it')])
            await c.deployAgent({
                slug: 'open-channel',
                spec: {
                    triggers: [
                        {
                            type: 'chat',
                            config: {},
                            auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                        },
                        trigger({ mention_only: false, auto_resume_threads: false }),
                    ],
                    auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                },
                encrypted_env: SLACK_ENV,
            })
            const res = await c.slackPost(
                'open-channel',
                'events',
                slackEvent({ eventType: 'message', text: 'random chatter' }),
                SLACK_SECRET
            )
            expect(res.status).toBe(200)
            expect(res.body.session_id).toBeTruthy()
        })

        it('mention_only=true: app_mention accepted, plain message dropped', async () => {
            await c.deployAgent({
                slug: 'gated-mention',
                spec: {
                    triggers: [
                        {
                            type: 'chat',
                            config: {},
                            auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                        },
                        trigger({ mention_only: true, auto_resume_threads: false }),
                    ],
                    auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                },
                encrypted_env: SLACK_ENV,
            })
            // Plain message → dropped with structured reason; no session id.
            const drop = await c.slackPost(
                'gated-mention',
                'events',
                slackEvent({ eventType: 'message', text: 'hey there' }),
                SLACK_SECRET
            )
            expect(drop.status).toBe(200)
            expect(drop.body.dropped).toBe('mention_only')
            expect(drop.body.session_id).toBeUndefined()
            // app_mention → enqueued.
            c.setScript([fauxText('hi')])
            const accept = await c.slackPost(
                'gated-mention',
                'events',
                slackEvent({ eventType: 'app_mention', text: '<@U0BOT> hello' }),
                SLACK_SECRET
            )
            expect(accept.status).toBe(200)
            expect(accept.body.session_id).toBeTruthy()
        })

        it('mention_only=true + auto_resume_threads=true: non-mention reply accepted when thread has an existing session', async () => {
            // First turn: @-mention seeds a session keyed by thread_ts.
            // Second turn: same thread_ts, plain message (no @-mention).
            // The ingress should resume the same session and the seed message
            // should carry `mention: false` so the model knows to judge intent.
            c.setScript([fauxText('first reply'), fauxText('second reply')])
            await c.deployAgent({
                slug: 'thread-resume',
                spec: {
                    triggers: [
                        {
                            type: 'chat',
                            config: {},
                            auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                        },
                        trigger({ mention_only: true, auto_resume_threads: true }),
                    ],
                    auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                },
                encrypted_env: SLACK_ENV,
            })
            const first = await c.slackPost(
                'thread-resume',
                'events',
                slackEvent({ eventType: 'app_mention', text: '<@U0BOT> kick off', ts: '100.0' }),
                SLACK_SECRET
            )
            expect(first.status).toBe(200)
            expect(first.body.session_id).toBeTruthy()
            await c.drain()

            // Same thread (thread_ts === first.ts), plain message.
            const second = await c.slackPost(
                'thread-resume',
                'events',
                slackEvent({
                    eventType: 'message',
                    text: 'follow-up without a mention',
                    ts: '101.0',
                    thread_ts: '100.0',
                }),
                SLACK_SECRET
            )
            expect(second.status).toBe(200)
            expect(second.body.session_id).toBe(first.body.session_id)
            expect(second.body.resumed).toBe(true)
            expect(second.body.dropped).toBeUndefined()
            await c.drain()
            // Seed for the resumed turn should flag mention=false.
            const session = await c.queue.get(first.body.session_id)
            const userTurns = session!.conversation.filter((m) => m.role === 'user') as Array<{
                role: 'user'
                content: string
            }>
            expect(userTurns).toHaveLength(2)
            expect(userTurns[0].content).toContain('mention: true')
            expect(userTurns[1].content).toContain('mention: false')
            expect(userTurns[1].content).toContain('resumed_owned_thread: true')
        })

        it('mention_only=true + auto_resume_threads=true: non-mention reply DROPPED when thread has no owned session', async () => {
            // The gate must not turn into "accept any message that has a
            // thread_ts" — only threads the bot already owns get through.
            await c.deployAgent({
                slug: 'thread-resume-strict',
                spec: {
                    triggers: [
                        {
                            type: 'chat',
                            config: {},
                            auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                        },
                        trigger({ mention_only: true, auto_resume_threads: true }),
                    ],
                    auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                },
                encrypted_env: SLACK_ENV,
            })
            const res = await c.slackPost(
                'thread-resume-strict',
                'events',
                slackEvent({
                    eventType: 'message',
                    text: 'two humans in a thread the bot has never seen',
                    ts: '200.1',
                    thread_ts: '200.0',
                }),
                SLACK_SECRET
            )
            expect(res.status).toBe(200)
            expect(res.body.dropped).toBe('mention_only_no_owned_thread')
            expect(res.body.session_id).toBeUndefined()
        })
    })

    describe('allow_direct_messages', () => {
        /** Slack trigger with a DM surface, optionally still gating channel
         *  messages behind @-mentions. */
        function dmSpec(opts: { allow_direct_messages: boolean; mention_only?: boolean }): Record<string, unknown> {
            return {
                triggers: [
                    {
                        type: 'slack',
                        config: {
                            mention_only: opts.mention_only ?? true,
                            auto_resume_threads: false,
                            allow_direct_messages: opts.allow_direct_messages,
                            trusted_workspaces: '*',
                        },
                    },
                ],
                auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
            }
        }

        it('DM (channel_type=im) enqueues a session even under mention_only', async () => {
            // A DM is inherently directed at the bot — it must bypass the
            // mention_only drop that would reject a plain channel message.
            c.setScript([fauxText('dm reply')])
            await c.deployAgent({
                slug: 'dm-bot',
                spec: dmSpec({ allow_direct_messages: true, mention_only: true }),
                encrypted_env: SLACK_ENV,
            })
            const res = await c.slackPost(
                'dm-bot',
                'events',
                slackEvent({ eventType: 'message', channel_type: 'im', channel: 'D01', text: 'hey bot' }),
                SLACK_SECRET
            )
            expect(res.status).toBe(200)
            expect(res.body.session_id).toBeTruthy()
            expect(res.body.dropped).toBeUndefined()

            await c.drain()
            const session = await c.queue.get(res.body.session_id)
            const userMsg = session!.conversation.find((m) => m.role === 'user') as
                | { role: 'user'; content: string }
                | undefined
            // Seed flags the 1:1 so the model knows there's no @-mention.
            expect(userMsg?.content).toMatch(/^dm: true$/m)
            expect(userMsg?.content).toContain('hey bot')
        })

        it('second DM in the same channel resumes the same session (stable per-channel key)', async () => {
            c.setScript([fauxText('first'), fauxText('second')])
            await c.deployAgent({
                slug: 'dm-resume',
                spec: dmSpec({ allow_direct_messages: true }),
                encrypted_env: SLACK_ENV,
            })
            const first = await c.slackPost(
                'dm-resume',
                'events',
                slackEvent({ eventType: 'message', channel_type: 'im', channel: 'D01', text: 'one', ts: '1.0' }),
                SLACK_SECRET
            )
            expect(first.body.resumed).toBe(false)
            await c.drain()

            // No thread_ts — a DM keys per-channel, so the second message lands
            // on the same session.
            const second = await c.slackPost(
                'dm-resume',
                'events',
                slackEvent({ eventType: 'message', channel_type: 'im', channel: 'D01', text: 'two', ts: '2.0' }),
                SLACK_SECRET
            )
            expect(second.body.resumed).toBe(true)
            expect(second.body.session_id).toBe(first.body.session_id)
        })

        it('DM dropped when allow_direct_messages is false', async () => {
            await c.deployAgent({
                slug: 'dm-disabled',
                spec: dmSpec({ allow_direct_messages: false }),
                encrypted_env: SLACK_ENV,
            })
            const res = await c.slackPost(
                'dm-disabled',
                'events',
                slackEvent({ eventType: 'message', channel_type: 'im', channel: 'D01', text: 'anyone home?' }),
                SLACK_SECRET
            )
            expect(res.status).toBe(200)
            expect(res.body.dropped).toBe('dm_not_enabled')
            expect(res.body.session_id).toBeUndefined()
        })
    })

    describe('ack_reaction', () => {
        /** Tests need their own cluster + http recorder so we can intercept
         *  the fire-and-forget `reactions.add` call before it hits slack.com.
         *  The outer harness's default HttpClient hits the real wire — fine
         *  for tests that don't care, but the ack flow specifically needs
         *  to be intercepted to be assertable. */
        async function ackCluster(): Promise<{
            cc: Cluster
            slackCalls: Array<{ url: string; body: Record<string, unknown> }>
            failNext: (status?: number) => void
        }> {
            const slackCalls: Array<{ url: string; body: Record<string, unknown> }> = []
            let nextFailStatus: number | null = null
            const recorder = {
                fetch: (input: string | URL, init?: RequestInit): Promise<Response> => {
                    const url = typeof input === 'string' ? input : input.toString()
                    if (url.includes('slack.com/api/')) {
                        slackCalls.push({
                            url,
                            body: typeof init?.body === 'string' ? JSON.parse(init.body) : {},
                        })
                        if (nextFailStatus != null) {
                            const status = nextFailStatus
                            nextFailStatus = null
                            return Promise.resolve({
                                ok: status >= 200 && status < 300,
                                status,
                                json: async () => ({ ok: false, error: 'simulated_failure' }),
                                text: async () => '{"ok":false,"error":"simulated_failure"}',
                            } as unknown as Response)
                        }
                        return Promise.resolve({
                            ok: true,
                            status: 200,
                            json: async () => ({ ok: true }),
                            text: async () => '{"ok":true}',
                        } as unknown as Response)
                    }
                    return Promise.reject(new Error(`unexpected fetch in test: ${url}`))
                },
            }
            const cc = await buildCluster({ http: recorder })
            return {
                cc,
                slackCalls,
                failNext: (status = 500) => {
                    nextFailStatus = status
                },
            }
        }

        it('fires reactions.add with the configured emoji on app_mention, with bot-token bearer auth', async () => {
            const { cc, slackCalls } = await ackCluster()
            try {
                await cc.deployAgent({
                    slug: 'acker',
                    spec: {
                        triggers: [
                            {
                                type: 'chat',
                                config: {},
                                auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                            },
                            {
                                type: 'slack',
                                config: {
                                    mention_only: false,
                                    auto_resume_threads: false,
                                    ack_reaction: 'eyes',
                                    trusted_workspaces: '*',
                                },
                            },
                        ],
                        auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                    },
                    encrypted_env: { ...SLACK_ENV, SLACK_BOT_TOKEN: 'xoxb-acker' },
                })
                cc.setScript([fauxText('done')])
                const res = await cc.slackPost(
                    'acker',
                    'events',
                    slackEvent({ eventType: 'app_mention', text: '<@U0BOT> hi', ts: '300.0' }),
                    SLACK_SECRET
                )
                expect(res.status).toBe(200)
                expect(res.body.session_id).toBeTruthy()
                // Reaction is fire-and-forget; let the microtask queue drain.
                await new Promise((r) => setTimeout(r, 50))
                const reactionCalls = slackCalls.filter((c) => c.url.endsWith('reactions.add'))
                expect(reactionCalls).toHaveLength(1)
                expect(reactionCalls[0].body).toMatchObject({
                    channel: 'C01',
                    timestamp: '300.0',
                    name: 'eyes',
                })
            } finally {
                await cc.teardown()
            }
        })

        it('no reaction posted when ack_reaction is unset (default)', async () => {
            const { cc, slackCalls } = await ackCluster()
            try {
                await cc.deployAgent({
                    slug: 'silent',
                    spec: {
                        triggers: [
                            {
                                type: 'chat',
                                config: {},
                                auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                            },
                            {
                                type: 'slack',
                                config: {
                                    mention_only: false,
                                    auto_resume_threads: false,
                                    trusted_workspaces: '*',
                                },
                            },
                        ],
                        auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                    },
                    encrypted_env: { ...SLACK_ENV, SLACK_BOT_TOKEN: 'xoxb-silent' },
                })
                cc.setScript([fauxText('done')])
                const res = await cc.slackPost(
                    'silent',
                    'events',
                    slackEvent({ eventType: 'app_mention', text: '<@U0BOT> hi' }),
                    SLACK_SECRET
                )
                expect(res.status).toBe(200)
                await new Promise((r) => setTimeout(r, 50))
                expect(slackCalls.filter((c) => c.url.endsWith('reactions.add'))).toHaveLength(0)
            } finally {
                await cc.teardown()
            }
        })

        it('fails open: slack returning 500 does not break the event handler', async () => {
            const { cc, slackCalls, failNext } = await ackCluster()
            try {
                await cc.deployAgent({
                    slug: 'resilient',
                    spec: {
                        triggers: [
                            {
                                type: 'chat',
                                config: {},
                                auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                            },
                            {
                                type: 'slack',
                                config: {
                                    mention_only: false,
                                    auto_resume_threads: false,
                                    ack_reaction: 'thinking_face',
                                    trusted_workspaces: '*',
                                },
                            },
                        ],
                        auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                    },
                    encrypted_env: { ...SLACK_ENV, SLACK_BOT_TOKEN: 'xoxb-resilient' },
                })
                cc.setScript([fauxText('done')])
                failNext(500)
                const res = await cc.slackPost(
                    'resilient',
                    'events',
                    slackEvent({ eventType: 'app_mention', text: '<@U0BOT> hi' }),
                    SLACK_SECRET
                )
                expect(res.status).toBe(200)
                expect(res.body.session_id).toBeTruthy()
                await new Promise((r) => setTimeout(r, 50))
                expect(slackCalls.filter((c) => c.url.endsWith('reactions.add'))).toHaveLength(1)
            } finally {
                await cc.teardown()
            }
        })

        it('no reaction posted when SLACK_BOT_TOKEN is unset (fail open, no crash)', async () => {
            const { cc, slackCalls } = await ackCluster()
            try {
                await cc.deployAgent({
                    slug: 'tokenless',
                    spec: {
                        triggers: [
                            {
                                type: 'chat',
                                config: {},
                                auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                            },
                            {
                                type: 'slack',
                                config: {
                                    mention_only: false,
                                    auto_resume_threads: false,
                                    ack_reaction: 'eyes',
                                    trusted_workspaces: '*',
                                },
                            },
                        ],
                        auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                    },
                    encrypted_env: SLACK_ENV, // signing secret only — no SLACK_BOT_TOKEN
                })
                cc.setScript([fauxText('done')])
                const res = await cc.slackPost(
                    'tokenless',
                    'events',
                    slackEvent({ eventType: 'app_mention', text: '<@U0BOT> hi' }),
                    SLACK_SECRET
                )
                expect(res.status).toBe(200)
                expect(res.body.session_id).toBeTruthy()
                await new Promise((r) => setTimeout(r, 50))
                expect(slackCalls.filter((c) => c.url.endsWith('reactions.add'))).toHaveLength(0)
            } finally {
                await cc.teardown()
            }
        })
    })

    describe('allow_workspace_participants', () => {
        /** Same http-recorder pattern as ack_reaction: the owner-only rejection
         *  reply posts chat.postMessage, which we intercept to assert on. */
        async function recorderCluster(): Promise<{
            cc: Cluster
            slackCalls: Array<{ url: string; body: Record<string, unknown> }>
        }> {
            const slackCalls: Array<{ url: string; body: Record<string, unknown> }> = []
            const recorder = {
                fetch: (input: string | URL, init?: RequestInit): Promise<Response> => {
                    const url = typeof input === 'string' ? input : input.toString()
                    if (url.includes('slack.com/api/')) {
                        slackCalls.push({
                            url,
                            body: typeof init?.body === 'string' ? JSON.parse(init.body) : {},
                        })
                        return Promise.resolve({
                            ok: true,
                            status: 200,
                            json: async () => ({ ok: true, ts: '0.1', channel: 'C01' }),
                            text: async () => '{"ok":true}',
                        } as unknown as Response)
                    }
                    return Promise.reject(new Error(`unexpected fetch in test: ${url}`))
                },
            }
            const cc = await buildCluster({ http: recorder })
            return { cc, slackCalls }
        }

        function ownerThreadSpec(allow: boolean): Record<string, unknown> {
            return {
                triggers: [
                    {
                        type: 'slack',
                        config: {
                            mention_only: true,
                            auto_resume_threads: true,
                            allow_workspace_participants: allow,
                            trusted_workspaces: '*',
                        },
                    },
                ],
                auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
            }
        }

        it('default (owner-only): a non-owner reply is rejected AND gets an in-thread explanation', async () => {
            const { cc, slackCalls } = await recorderCluster()
            try {
                cc.setScript([fauxText('alice first')])
                await cc.deployAgent({
                    slug: 'owner-only',
                    spec: ownerThreadSpec(false),
                    encrypted_env: { ...SLACK_ENV, SLACK_BOT_TOKEN: 'xoxb-owner-only' },
                })
                const first = await cc.slackPost(
                    'owner-only',
                    'events',
                    slackEvent({ eventType: 'app_mention', user: 'U-ALICE', text: '<@U0BOT> open', ts: '500.0' }),
                    SLACK_SECRET
                )
                expect(first.body.session_id).toBeTruthy()
                await cc.drain()

                const second = await cc.slackPost(
                    'owner-only',
                    'events',
                    slackEvent({
                        eventType: 'message',
                        user: 'U-BOB',
                        text: 'bob barges in',
                        ts: '501.0',
                        thread_ts: '500.0',
                    }),
                    SLACK_SECRET
                )
                expect(second.body.elevation_required).toBe(true)
                expect(second.body.resumed).toBe(false)
                // Bob's message must not reach the runner.
                const session = await cc.queue.get(first.body.session_id)
                expect(session!.pending_inputs).toHaveLength(0)
                // But Bob is told why, in the thread.
                const postCalls = slackCalls.filter((c) => c.url.endsWith('chat.postMessage'))
                expect(postCalls).toHaveLength(1)
                expect(postCalls[0].body).toMatchObject({ channel: 'C01', thread_ts: '500.0' })
                expect(String(postCalls[0].body.text)).toContain('started this thread')
            } finally {
                await cc.teardown()
            }
        })

        it('allow_workspace_participants=true: a non-owner advances the same thread (no elevation, no rejection reply)', async () => {
            const { cc, slackCalls } = await recorderCluster()
            try {
                cc.setScript([fauxText('alice first'), fauxText('reply to bob')])
                await cc.deployAgent({
                    slug: 'open-thread',
                    spec: ownerThreadSpec(true),
                    encrypted_env: { ...SLACK_ENV, SLACK_BOT_TOKEN: 'xoxb-open' },
                })
                const first = await cc.slackPost(
                    'open-thread',
                    'events',
                    slackEvent({ eventType: 'app_mention', user: 'U-ALICE', text: '<@U0BOT> open', ts: '600.0' }),
                    SLACK_SECRET
                )
                await cc.drain()

                const second = await cc.slackPost(
                    'open-thread',
                    'events',
                    slackEvent({
                        eventType: 'message',
                        user: 'U-BOB',
                        text: 'bob joins in',
                        ts: '601.0',
                        thread_ts: '600.0',
                    }),
                    SLACK_SECRET
                )
                expect(second.body.session_id).toBe(first.body.session_id)
                expect(second.body.resumed).toBe(true)
                expect(second.body.elevation_required).toBeUndefined()
                await cc.drain()

                const session = await cc.queue.get(first.body.session_id)
                const userTurns = session!.conversation.filter((m) => m.role === 'user') as Array<{
                    role: 'user'
                    content: string
                    sender?: { kind: string; slack_user_id?: string }
                }>
                expect(userTurns).toHaveLength(2)
                expect(userTurns[1].content).toContain('bob joins in')
                // The real sender is preserved for audit even though the session
                // is owned by Alice.
                expect(userTurns[1].sender).toMatchObject({ kind: 'slack', slack_user_id: 'U-BOB' })
                // No rejection reply when the thread is open to the workspace.
                expect(slackCalls.filter((c) => c.url.endsWith('chat.postMessage'))).toHaveLength(0)
            } finally {
                await cc.teardown()
            }
        })
    })

    describe('assistant reply relay', () => {
        /** Same http-recorder pattern: intercept the relay's chat.postMessage
         *  before it hits slack.com so we can assert the reply text lands in the
         *  thread. */
        async function recorderCluster(secrets: Record<string, string> = {}): Promise<{
            cc: Cluster
            slackCalls: Array<{ url: string; body: Record<string, unknown> }>
        }> {
            const slackCalls: Array<{ url: string; body: Record<string, unknown> }> = []
            const recorder = {
                fetch: (input: string | URL, init?: RequestInit): Promise<Response> => {
                    const url = typeof input === 'string' ? input : input.toString()
                    if (url.includes('slack.com/api/')) {
                        slackCalls.push({
                            url,
                            body: typeof init?.body === 'string' ? JSON.parse(init.body) : {},
                        })
                        return Promise.resolve({
                            ok: true,
                            status: 200,
                            // ts lets the status reporter track + delete its message.
                            json: async () => ({ ok: true, ts: 'TS_STATUS' }),
                            text: async () => '{"ok":true,"ts":"TS_STATUS"}',
                        } as unknown as Response)
                    }
                    return Promise.reject(new Error(`unexpected fetch in test: ${url}`))
                },
            }
            // The runner reads the bot token from `deps.secrets` — the same map
            // `makeEncryptedEnvResolver` decrypts from `encrypted_env` in prod and
            // that the slack tools read via `ctx.secret`. The harness defaults
            // resolveSecrets to empty, so wire it explicitly here.
            const cc = await buildCluster({ http: recorder, resolveSecrets: async () => secrets })
            return { cc, slackCalls }
        }

        function slackSpec(): Record<string, unknown> {
            return {
                triggers: [
                    {
                        type: 'slack',
                        config: { mention_only: false, auto_resume_threads: false, trusted_workspaces: '*' },
                    },
                ],
                auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
            }
        }

        it('posts each finalized assistant message into the thread — no tool call needed', async () => {
            const { cc, slackCalls } = await recorderCluster({ SLACK_BOT_TOKEN: 'xoxb-relayer' })
            try {
                cc.setScript([fauxText('the valuable answer')])
                await cc.deployAgent({
                    slug: 'relayer',
                    spec: slackSpec(),
                    encrypted_env: { ...SLACK_ENV, SLACK_BOT_TOKEN: 'xoxb-relayer' },
                })
                const res = await cc.slackPost(
                    'relayer',
                    'events',
                    slackEvent({ channel: 'C01', text: 'help', ts: '700.0', thread_ts: '700.0' }),
                    SLACK_SECRET
                )
                expect(res.status).toBe(200)
                await cc.drain()

                // While working: a "working on it" status is posted, then removed
                // before the real reply lands so the reply is the latest message.
                const statusPosts = slackCalls.filter(
                    (c) => c.url.endsWith('chat.postMessage') && String(c.body.text).includes('Working on it')
                )
                expect(statusPosts).toHaveLength(1)
                expect(slackCalls.filter((c) => c.url.endsWith('chat.delete'))).toHaveLength(1)

                const replyPosts = slackCalls.filter(
                    (c) => c.url.endsWith('chat.postMessage') && c.body.text === 'the valuable answer'
                )
                expect(replyPosts).toHaveLength(1)
                expect(replyPosts[0].body).toMatchObject({ channel: 'C01', thread_ts: '700.0' })
            } finally {
                await cc.teardown()
            }
        })

        it('does not relay when the bot token is unset (logged, no crash)', async () => {
            const { cc, slackCalls } = await recorderCluster()
            try {
                cc.setScript([fauxText('answer with no token')])
                await cc.deployAgent({
                    slug: 'relayer-tokenless',
                    spec: slackSpec(),
                    encrypted_env: SLACK_ENV, // signing secret only — no SLACK_BOT_TOKEN
                })
                const res = await cc.slackPost(
                    'relayer-tokenless',
                    'events',
                    slackEvent({ channel: 'C01', text: 'help', ts: '710.0', thread_ts: '710.0' }),
                    SLACK_SECRET
                )
                expect(res.status).toBe(200)
                await cc.drain()
                // Session still completes; nothing posted to slack.
                expect((await cc.queue.get(res.body.session_id))!.state).toBe('completed')
                expect(slackCalls.filter((c) => c.url.endsWith('chat.postMessage'))).toHaveLength(0)
            } finally {
                await cc.teardown()
            }
        })
    })
})
