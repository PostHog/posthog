/**
 * Worker resume: when a worker crashes mid-turn the session row stays in
 * 'running' state with a stale claimed_at. The janitor's reaper re-queues
 * those rows so a sibling worker picks them up and continues from the
 * persisted conversation.
 *
 * Old equivalent: persistent-chat/worker-resume.test.ts.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

describe('worker resume after crash: real e2e', () => {
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

    it('a session left in "running" with a stale claimed_at is re-queued by the sweep', async () => {
        c.setScript([fauxText('done')])
        const { revision } = await c.deployAgent({ slug: 'crashy' })

        // Inject a session that LOOKS like a worker crashed mid-turn:
        //   - state = 'running'
        //   - claimed_at = an hour ago
        //   - conversation already has the user message
        const sessionId = '00000000-0000-0000-0000-deadbeef0001'
        const longAgo = new Date(Date.now() - 60 * 60_000).toISOString()
        await c.pool.query(
            `INSERT INTO agent_session
                (id, application_id, revision_id, team_id, state, conversation, pending_inputs,
                 claimed_at, created_at, updated_at)
             VALUES ($1, $2, $3, 1, 'running', $4::jsonb, '[]'::jsonb, $5, $5, $5)`,
            [
                sessionId,
                revision.application_id,
                revision.id,
                JSON.stringify([{ role: 'user', content: 'crashed mid turn', timestamp: Date.parse(longAgo) }]),
                longAgo,
            ]
        )

        // Sweep: any session running > 60s gets re-queued.
        const reapResp = await request(c.janitor).post('/sweep')
        expect(reapResp.body.requeued).toBe(1)

        // State is now 'queued'; drain runs the turn and completes.
        let row = await c.queue.get(sessionId)
        expect(row!.state).toBe('queued')

        await c.drain()
        row = await c.queue.get(sessionId)
        expect(row!.state).toBe('completed')
        // Conversation survived the "crash" — the user message is still there.
        const userMsgs = row!.conversation.filter((m) => m.role === 'user')
        expect(userMsgs[0].content).toBe('crashed mid turn')
    })

    it('a recently-claimed running session is NOT reaped', async () => {
        const { revision } = await c.deployAgent({ slug: 'fresh' })
        const sessionId = '00000000-0000-0000-0000-deadbeef0002'
        await c.pool.query(
            `INSERT INTO agent_session
                (id, application_id, revision_id, team_id, state, conversation, pending_inputs,
                 claimed_at, created_at, updated_at)
             VALUES ($1, $2, $3, 1, 'running', '[]'::jsonb, '[]'::jsonb, NOW(), NOW(), NOW())`,
            [sessionId, revision.application_id, revision.id]
        )
        const reapResp = await request(c.janitor).post('/sweep')
        expect(reapResp.body.requeued).toBe(0)
        const row = await c.queue.get(sessionId)
        expect(row!.state).toBe('running')
    })
})
