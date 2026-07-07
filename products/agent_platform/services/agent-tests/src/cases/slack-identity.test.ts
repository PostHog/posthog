/**
 * Slack identity: trusted_workspaces gating + stable AgentUser id per
 * (workspace, user) tuple across sessions.
 *
 * Old equivalent: isolated/slack-identity.test.ts.
 */

import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

const SLACK_SECRET = 'test-slack-secret'
const SLACK_ENV = { SLACK_SIGNING_SECRET: SLACK_SECRET }

function slackEvent(opts: {
    channel?: string
    team?: string
    user?: string
    text?: string
    ts?: string
    thread_ts?: string
}): Record<string, unknown> {
    return {
        type: 'event_callback',
        event: {
            type: 'message',
            channel: opts.channel ?? 'C01',
            team: opts.team ?? 'T01',
            user: opts.user ?? 'U01',
            text: opts.text ?? 'hi',
            ts: opts.ts ?? '1.0',
            thread_ts: opts.thread_ts,
        },
    }
}

describe('slack identity: real e2e', () => {
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

    it('trusted workspace → 200 + AgentUser row persisted', async () => {
        c.setScript([fauxText('hello')])
        const { application } = await c.deployAgent({
            slug: 'trusted',
            spec: { triggers: [{ type: 'slack', config: { trusted_workspaces: ['T01'] } }] },
            encrypted_env: SLACK_ENV,
        })
        const res = await c.slackPost('trusted', 'events', slackEvent({ team: 'T01', user: 'U01' }), SLACK_SECRET)
        expect(res.status).toBe(200)

        const agentUser = await c.identities.find({
            application_id: application.id,
            principal_kind: 'slack',
            principal_id: 'T01:U01',
        })
        expect(agentUser).not.toBeNull()

        const sessions = await c.queue.listForApplication(application.id)
        const principal = sessions[0].principal
        expect(principal?.kind).toBe('slack')
        if (principal?.kind === 'slack') {
            expect(principal.agent_user_id).toBe(agentUser!.id)
        }
    })

    it('untrusted workspace on a trusted-list agent → 200 ack + drop (never a 4xx delivery failure)', async () => {
        await c.deployAgent({
            slug: 'gated',
            spec: { triggers: [{ type: 'slack', config: { trusted_workspaces: ['T-OK-ONLY'] } }] },
            encrypted_env: SLACK_ENV,
        })
        const res = await c.slackPost('gated', 'events', slackEvent({ team: 'T-EVIL', user: 'U-EVIL' }), SLACK_SECRET)
        // A signed, authenticated delivery that just isn't from a trusted
        // workspace is a routing decision, not a delivery failure — Slack (and
        // any provider) retries non-2xx responses, so this must ack.
        expect(res.status).toBe(200)
        expect(res.body.dropped).toBe('workspace_not_trusted')
    })

    it('"*" accepts any workspace; distinct (workspace, user) → distinct AgentUsers', async () => {
        c.setScript([fauxText('one'), fauxText('two')])
        const { application } = await c.deployAgent({
            slug: 'open',
            spec: { triggers: [{ type: 'slack', config: { trusted_workspaces: '*' } }] },
            encrypted_env: SLACK_ENV,
        })

        await c.slackPost(
            'open',
            'events',
            slackEvent({ team: 'T-A', user: 'U-1', ts: '1.0', thread_ts: '1.0' }),
            SLACK_SECRET
        )
        await c.slackPost(
            'open',
            'events',
            slackEvent({ team: 'T-B', user: 'U-2', ts: '2.0', thread_ts: '2.0' }),
            SLACK_SECRET
        )

        const a = await c.identities.find({
            application_id: application.id,
            principal_kind: 'slack',
            principal_id: 'T-A:U-1',
        })
        const b = await c.identities.find({
            application_id: application.id,
            principal_kind: 'slack',
            principal_id: 'T-B:U-2',
        })
        expect(a).not.toBeNull()
        expect(b).not.toBeNull()
        expect(a!.id).not.toBe(b!.id)
    })

    it('same (workspace, user) tuple resolves to the same AgentUser across sessions', async () => {
        c.setScript([fauxText('first'), fauxText('second')])
        const { application } = await c.deployAgent({
            slug: 'stable',
            spec: { triggers: [{ type: 'slack', config: { trusted_workspaces: '*' } }] },
            encrypted_env: SLACK_ENV,
        })

        // Two events from the same user, distinct threads → distinct sessions
        // but the AgentUser row is the same.
        await c.slackPost(
            'stable',
            'events',
            slackEvent({ team: 'T-X', user: 'U-stable', ts: '1.0', thread_ts: '1.0' }),
            SLACK_SECRET
        )
        await c.drain()
        await c.slackPost(
            'stable',
            'events',
            slackEvent({ team: 'T-X', user: 'U-stable', ts: '2.0', thread_ts: '2.0' }),
            SLACK_SECRET
        )
        await c.drain()

        const sessions = await c.queue.listForApplication(application.id)
        // Different sessions...
        expect(new Set(sessions.map((s) => s.id)).size).toBe(2)
        // ...but same AgentUser id stamped on both principals.
        const principalIds = sessions.map((s) => (s.principal?.kind === 'slack' ? s.principal.agent_user_id : null))
        expect(principalIds[0]).toBe(principalIds[1])
        expect(principalIds[0]).toBeTruthy()
    })
})
