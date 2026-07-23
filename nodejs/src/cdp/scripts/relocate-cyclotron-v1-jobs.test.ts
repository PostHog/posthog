import { Pool } from 'pg'
import { v4 as uuidv4 } from 'uuid'
import { gzipSync } from 'zlib'

import { CyclotronJobQueuePostgresV2 } from '../services/job-queue/job-queue-postgres-v2'
import { RelocateDeps, buildV2Config, relocate } from './relocate-cyclotron-v1-jobs'

// Real V1 (legacy postgres) and V2 (cyclotron-node) test databases — the same pair the
// migrate-entry test bootstrap creates. These tests exercise the relocation end-to-end:
// real rows written to V1, relocated through the real V2 producer, verified in V2, deleted
// from V1.
const V1_DB_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron'
const V2_DB_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

// Dedicated queue name so parallel test files touching real 'hogflow' rows can't interfere.
const QUEUE = 'hogflow_relocate_e2e'

const YEAR_MS = 365 * 24 * 60 * 60 * 1000

interface V1RowSpec {
    id?: string
    teamId?: number
    functionId?: string | null
    priority?: number
    parentRunId?: string | null
    scheduled: Date
    // vm_state bytes exactly as they sit in the column (plain JSON or gzip'd).
    vmState?: Buffer | null
}

describe('relocate-cyclotron-v1-jobs (e2e)', () => {
    let v1: Pool
    let v2Pool: Pool
    let v2Queue: CyclotronJobQueuePostgresV2

    // Whole-second future time so timestamptz <-> JS Date round-trips exactly.
    const futureDate = (msFromNow: number): Date => new Date(Math.floor((Date.now() + msFromNow) / 1000) * 1000)

    const insertV1Row = async (spec: V1RowSpec): Promise<string> => {
        const id = spec.id ?? uuidv4()
        await v1.query(
            `INSERT INTO cyclotron_jobs
                (id, team_id, function_id, created, janitor_touch_count, transition_count, last_transition,
                 queue_name, state, scheduled, priority, parent_run_id, vm_state, metadata, parameters, blob)
             VALUES ($1, $2, $3, now(), 0, 0, now(), $4, 'available', $5, $6, $7, $8, NULL, NULL, NULL)`,
            [
                id,
                spec.teamId ?? 1,
                spec.functionId ?? uuidv4(),
                QUEUE,
                spec.scheduled,
                spec.priority ?? 0,
                spec.parentRunId ?? null,
                spec.vmState === undefined ? Buffer.from(JSON.stringify({})) : spec.vmState,
            ]
        )
        return id
    }

    const v1AvailableIds = async (): Promise<string[]> => {
        const res = await v1.query<{ id: string }>(
            `SELECT id FROM cyclotron_jobs WHERE queue_name = $1 AND state = 'available' ORDER BY id`,
            [QUEUE]
        )
        return res.rows.map((r) => r.id)
    }

    const readV2Row = async (
        id: string
    ): Promise<{
        id: string
        function_id: string | null
        priority: number
        scheduled: Date
        parent_run_id: string | null
        status: string
        distinct_id: string | null
        person_id: string | null
        action_id: string | null
        state: Record<string, any> | null
    } | null> => {
        const res = await v2Pool.query(
            `SELECT id, function_id, priority, scheduled, parent_run_id, status,
                    distinct_id, person_id, action_id, state
             FROM cyclotron_jobs WHERE id = $1`,
            [id]
        )
        if (res.rows.length === 0) {
            return null
        }
        const row = res.rows[0]
        return { ...row, state: row.state ? JSON.parse(row.state.toString('utf-8')) : null }
    }

    const cleanup = async (): Promise<void> => {
        await v1.query(`DELETE FROM cyclotron_jobs WHERE queue_name = $1`, [QUEUE])
        await v2Pool.query(`DELETE FROM cyclotron_jobs WHERE queue_name = $1`, [QUEUE])
    }

    beforeAll(async () => {
        v1 = new Pool({ connectionString: V1_DB_URL })
        v2Pool = new Pool({ connectionString: V2_DB_URL })
        v2Queue = new CyclotronJobQueuePostgresV2(1, buildV2Config(V2_DB_URL))
    })

    afterAll(async () => {
        await cleanup()
        await v2Queue.stopProducer().catch(() => undefined)
        await v1.end()
        await v2Pool.end()
    })

    beforeEach(cleanup)

    const deps = (): RelocateDeps => ({ v1, v2Pool, v2Queue })

    it('relocates legit rows to V2 (preserving id, schedule, payload) and deletes corrupt rows', async () => {
        const scheduledSoon = futureDate(30 * 24 * 60 * 60 * 1000) // 30 days
        const functionId = uuidv4()
        const parentRunId = uuidv4()
        const vmState = {
            event: { distinct_id: 'de2e-user' },
            personId: 'de2e-person',
            currentAction: { id: 'de2e-action' },
            variables: { greeting: 'hi' },
            actionStepCount: 3,
        }

        const legitPlain = await insertV1Row({
            scheduled: scheduledSoon,
            priority: 7,
            functionId,
            parentRunId,
            vmState: Buffer.from(JSON.stringify(vmState)),
        })
        // Second legit row with a GZIP-compressed vm_state — must be decoded transparently.
        const gzipState = { event: { distinct_id: 'gz-user' }, currentAction: { id: 'gz-action' } }
        const legitGzip = await insertV1Row({
            scheduled: futureDate(80 * 24 * 60 * 60 * 1000),
            vmState: gzipSync(Buffer.from(JSON.stringify(gzipState))),
        })
        // Corrupt: scheduled beyond the 1-year cutoff — deleted, never relocated.
        const corrupt = await insertV1Row({ scheduled: futureDate(2 * YEAR_MS) })

        const result = await relocate(deps(), { queue: QUEUE, envLabel: 'test', apply: true })

        expect(result).toMatchObject({
            legitCount: 2,
            corruptCount: 1,
            relocated: 2,
            deletedCorrupt: 1,
            remaining: 0,
            missingIds: [],
            applied: true,
        })
        expect(result.verifiedIds.sort()).toEqual([legitPlain, legitGzip].sort())

        // V1 fully drained for this queue.
        expect(await v1AvailableIds()).toEqual([])

        // Plain legit row landed in V2 with every field preserved and state decoded.
        const v2Plain = await readV2Row(legitPlain)
        expect(v2Plain).not.toBeNull()
        expect(v2Plain!.status).toBe('available')
        expect(v2Plain!.function_id).toBe(functionId)
        expect(v2Plain!.priority).toBe(7)
        expect(v2Plain!.parent_run_id).toBe(parentRunId)
        expect(v2Plain!.scheduled.getTime()).toBe(scheduledSoon.getTime())
        expect(v2Plain!.state?.state).toEqual(vmState)
        // Lookup columns derived from the payload.
        expect(v2Plain!.distinct_id).toBe('de2e-user')
        expect(v2Plain!.person_id).toBe('de2e-person')
        expect(v2Plain!.action_id).toBe('de2e-action')

        // Gzip'd vm_state decoded end-to-end.
        const v2Gzip = await readV2Row(legitGzip)
        expect(v2Gzip!.state?.state).toEqual(gzipState)
        expect(v2Gzip!.distinct_id).toBe('gz-user')

        // Corrupt row never written to V2.
        expect(await readV2Row(corrupt)).toBeNull()
    })

    it('dry-run reports counts but writes and deletes nothing', async () => {
        const legit = await insertV1Row({ scheduled: futureDate(10 * 24 * 60 * 60 * 1000) })
        const corrupt = await insertV1Row({ scheduled: futureDate(2 * YEAR_MS) })

        const result = await relocate(deps(), { queue: QUEUE, envLabel: 'test', apply: false })

        expect(result).toMatchObject({
            legitCount: 1,
            corruptCount: 1,
            relocated: 0,
            deletedCorrupt: 0,
            applied: false,
        })

        // Nothing moved: both rows still in V1, neither in V2.
        expect((await v1AvailableIds()).sort()).toEqual([legit, corrupt].sort())
        expect(await readV2Row(legit)).toBeNull()
    })

    it('is idempotent: a second apply after a full drain is a no-op', async () => {
        await insertV1Row({ scheduled: futureDate(15 * 24 * 60 * 60 * 1000) })
        await insertV1Row({ scheduled: futureDate(15 * 24 * 60 * 60 * 1000) })
        await insertV1Row({ scheduled: futureDate(2 * YEAR_MS) })

        const first = await relocate(deps(), { queue: QUEUE, envLabel: 'test', apply: true })
        expect(first).toMatchObject({ relocated: 2, deletedCorrupt: 1, remaining: 0 })

        const second = await relocate(deps(), { queue: QUEUE, envLabel: 'test', apply: true })
        expect(second).toMatchObject({
            legitCount: 0,
            corruptCount: 0,
            relocated: 0,
            deletedCorrupt: 0,
            remaining: 0,
        })
    })

    it('drains a straggler whose id is already present + active in V2 (overwrite conflict)', async () => {
        const id = uuidv4()
        const scheduled = futureDate(20 * 24 * 60 * 60 * 1000)

        // First pass: relocate id into V2 (now 'available' = active) and remove it from V1.
        await insertV1Row({ id, scheduled })
        await relocate(deps(), { queue: QUEUE, envLabel: 'test', apply: true })
        expect(await readV2Row(id)).not.toBeNull()
        expect(await v1AvailableIds()).toEqual([])

        // A straggler with the same id shows up in V1 again. overwriteExisting refuses to
        // clobber the still-active V2 row (CyclotronJobConflictError), but the row is already
        // in V2 — so it passes the verification gate and is drained from V1 without error.
        await insertV1Row({ id, scheduled })
        const result = await relocate(deps(), { queue: QUEUE, envLabel: 'test', apply: true })

        expect(result.verifiedIds).toEqual([id])
        expect(result.missingIds).toEqual([])
        expect(result.remaining).toBe(0)
        expect(await v1AvailableIds()).toEqual([])
    })

    it('never deletes from V1 when the V2 write fails (safety gate)', async () => {
        const legit = await insertV1Row({ scheduled: futureDate(25 * 24 * 60 * 60 * 1000) })
        const corrupt = await insertV1Row({ scheduled: futureDate(2 * YEAR_MS) })

        // A V2 producer whose depth limit is 0 rejects every insert as "queue full". That is
        // a non-conflict error, so relocate must propagate it and leave V1 untouched — the
        // corrupt delete (which runs after the relocate block) must not run either.
        const brokenQueue = new CyclotronJobQueuePostgresV2(1, {
            ...buildV2Config(V2_DB_URL),
            CYCLOTRON_SHARD_DEPTH_LIMIT: 0,
        })
        try {
            await expect(
                relocate({ v1, v2Pool, v2Queue: brokenQueue }, { queue: QUEUE, envLabel: 'test', apply: true })
            ).rejects.toThrow()
        } finally {
            await brokenQueue.stopProducer().catch(() => undefined)
        }

        // Both rows still in V1, nothing in V2.
        expect((await v1AvailableIds()).sort()).toEqual([legit, corrupt].sort())
        expect(await readV2Row(legit)).toBeNull()
    })
})
