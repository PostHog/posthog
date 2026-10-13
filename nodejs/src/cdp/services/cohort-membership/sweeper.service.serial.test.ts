import { Message } from 'node-rdkafka'

import { defaultConfig } from '~/common/config/config'
import { KAFKA_COHORT_RECONCILE_MARKERS } from '~/common/config/kafka-topics'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'

import { resetBehavioralCohortsDatabase } from '../../../../tests/helpers/sql'
import {
    COHORT_PARTITION_COUNT,
    CohortMembershipSweepConfig,
    CohortMembershipSweeper,
    MembershipWatermarks,
} from './sweeper.service'

jest.setTimeout(30_000)

describe('CohortMembershipSweeper', () => {
    const TEAM_ID = 4242
    const COHORT_ID = 91204
    const MARKER_VERSION = '2026-05-26 12:30:00.000000'
    const THRESHOLD = '2026-05-26 12:00:00.000000'
    const BELOW_THRESHOLD = '2026-05-26 11:00:00.000000'
    const ABOVE_THRESHOLD = '2026-05-26 13:00:00.000000'
    /** What the column defaults to, so it is what every row written before the feature reads as. */
    const UNVERSIONED = '-infinity'

    const config: CohortMembershipSweepConfig = {
        COHORT_MEMBERSHIP_SWEEP_INTERVAL_MS: 60000,
        // Small enough that the batched delete loop has to iterate.
        COHORT_MEMBERSHIP_SWEEP_BATCH_SIZE: 2,
        COHORT_MEMBERSHIP_SWEEP_CLAIM_TIMEOUT_MS: 300000,
        COHORT_MEMBERSHIP_SWEEP_ABANDON_AFTER_DAYS: 3,
    }

    const CLUSTER = 'test-cluster'
    const TOPIC = 'cohort_membership_changed'

    let postgres: PostgresRouter
    let sweeper: CohortMembershipSweeper
    let watermarks: MembershipWatermarks
    let captureFailure: Error | null
    let runId: string

    beforeEach(async () => {
        postgres = new PostgresRouter(defaultConfig)
        await resetBehavioralCohortsDatabase(postgres)
        watermarks = { 0: 10 }
        captureFailure = null
        runId = new UUIDT().toString()
        sweeper = new CohortMembershipSweeper(config, postgres, {
            cluster: CLUSTER,
            topic: TOPIC,
            captureMembershipWatermarks: () =>
                captureFailure ? Promise.reject(captureFailure) : Promise.resolve(watermarks),
            refreshConsumerProgress: () => Promise.resolve(),
        })
    })

    afterEach(async () => {
        await postgres.end()
    })

    // The wire contract the Rust processor pins with golden bytes in
    // `rust/cohort-core/src/seed/reconcile.rs`.
    const markerMessage = (partition: number, overrides: Record<string, unknown> = {}): Message => ({
        value: Buffer.from(
            JSON.stringify({
                type: 'reconcile_complete',
                team_id: TEAM_ID,
                cohort_id: COHORT_ID,
                partition,
                run_id: runId,
                last_updated: MARKER_VERSION,
                ...overrides,
            })
        ),
        topic: KAFKA_COHORT_RECONCILE_MARKERS,
        partition: 0,
        offset: partition,
        timestamp: 0,
        size: 0,
        key: null,
    })

    const query = async <T>(sql: string, values?: any[]): Promise<T[]> => {
        const result = await postgres.query(PostgresUse.BEHAVIORAL_COHORTS_RW, sql, values, 'test')
        return result.rows as T[]
    }

    const readSweep = async (): Promise<Record<string, any>> => {
        const rows = await query<Record<string, any>>(
            `SELECT marker_bits, status, swept_rows, membership_hwms, membership_cluster, membership_topic,
                    to_char(min_marker_version, 'YYYY-MM-DD HH24:MI:SS.US') AS min_marker_version
             FROM cohort_membership_sweeps WHERE run_id = $1 AND cohort_id = $2`,
            [runId, COHORT_ID]
        )
        return rows[0]
    }

    const insertMembership = async (teamId: number, cohortId: number, version: string): Promise<string> => {
        const personId = new UUIDT().toString()
        await query(
            `INSERT INTO cohort_membership (team_id, cohort_id, person_id, in_cohort, version)
             VALUES ($1, $2, $3, true, $4::timestamp)`,
            [teamId, cohortId, personId, version]
        )
        return personId
    }

    const survivingPersonIds = async (): Promise<string[]> => {
        const rows = await query<{ person_id: string }>('SELECT person_id FROM cohort_membership ORDER BY person_id')
        return rows.map((row) => row.person_id)
    }

    /** A run whose markers are all in, with a snapshot minimum already folded in by the consumer. */
    const readyRun = async (): Promise<void> => {
        await query(
            `INSERT INTO cohort_membership_sweeps
                (run_id, cohort_id, team_id, marker_bits, min_marker_version, min_snapshot_version,
                 membership_hwms, membership_cluster, membership_topic, status, ready_at)
             VALUES ($1, $2, $3, -1, $4::timestamp, $5::timestamp, $6::jsonb, $7, $8, 'ready',
                     CURRENT_TIMESTAMP)`,
            [runId, COHORT_ID, TEAM_ID, MARKER_VERSION, THRESHOLD, JSON.stringify(watermarks), CLUSTER, TOPIC]
        )
    }

    const insertProgress = async (partition: number, nextOffset: number): Promise<void> => {
        await query(
            `INSERT INTO cohort_membership_consumer_progress (cluster, topic, partition, next_offset)
             VALUES ($1, $2, $3, $4)`,
            [CLUSTER, TOPIC, partition, nextOffset]
        )
    }

    /** Record the consumer as having applied everything the run's watermarks cover. */
    const openGate = async (): Promise<void> => {
        for (const [partition, highWatermark] of Object.entries(watermarks)) {
            await insertProgress(Number(partition), highWatermark)
        }
    }

    /** Run `onPage` after each delete page the sweep issues. */
    const afterEachDeletePage = (onPage: (page: number) => Promise<void> | void): void => {
        const realQuery = postgres.query.bind(postgres)
        let pages = 0
        postgres.query = (async (...args: any[]) => {
            const result = await (realQuery as any)(...args)
            if (args[3] === 'sweepCohortMembership') {
                await onPage(++pages)
            }
            return result
        }) as typeof postgres.query
    }

    it('should skip unusable markers instead of failing the batch', () => {
        const messages: Message[] = [
            markerMessage(0),
            { ...markerMessage(1), value: Buffer.from('not json') },
            markerMessage(2, { type: 'some_future_control_message' }),
            { ...markerMessage(3), value: null },
            markerMessage(4, { partition: COHORT_PARTITION_COUNT }),
            markerMessage(5, { run_id: 'not-a-uuid' }),
        ]

        const markers = sweeper.parseMarkers(messages)

        expect(markers.map((marker) => marker.partition)).toEqual([0])
    })

    it('should union marker bits and turn the run claimable only once the set is complete', async () => {
        const partitions = Array.from({ length: COHORT_PARTITION_COUNT }, (_, partition) => partition)

        await sweeper.applyMarkers(sweeper.parseMarkers(partitions.slice(0, -1).map((p) => markerMessage(p))))

        expect(await readSweep()).toMatchObject({ status: 'collecting', membership_hwms: null })

        // Redelivery must be a no-op, not an increment.
        await sweeper.applyMarkers(sweeper.parseMarkers([markerMessage(5), markerMessage(5)]))

        expect(await readSweep()).toMatchObject({ status: 'collecting' })

        // An incomplete set must not be promoted by the loop either.
        await sweeper.runOnce()

        expect(await readSweep()).toMatchObject({ status: 'collecting', membership_hwms: null })

        watermarks = { 0: 10, 3: 4 }
        // The last partition sets the sign bit, which is what completes the i64 bitmap. The
        // watermark capture and the 'ready' transition happen on the next sweep tick, not in the
        // marker batch, so a transient Kafka failure retries instead of killing the pod.
        await sweeper.applyMarkers(
            sweeper.parseMarkers([markerMessage(COHORT_PARTITION_COUNT - 1, { last_updated: ABOVE_THRESHOLD })])
        )

        expect(await readSweep()).toMatchObject({ marker_bits: '-1', status: 'collecting', membership_hwms: null })

        await sweeper.runOnce()

        expect(await readSweep()).toMatchObject({
            marker_bits: '-1',
            status: 'ready',
            membership_hwms: { 0: 10, 3: 4 },
            membership_cluster: CLUSTER,
            membership_topic: TOPIC,
            min_marker_version: MARKER_VERSION,
        })
    })

    it('should hold the sweep until consumer progress passes every captured watermark', async () => {
        // Partition 5 never had a message produced to it, so it also never gets a progress row.
        // The gate must skip it rather than wait on it: on a topic with idle partitions, waiting
        // would block every sweep forever.
        watermarks = { 0: 10, 3: 4, 5: 0 }
        await readyRun()
        const stale = await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)

        expect(await sweeper.runOnce()).toMatchObject({ swept: 0, blocked: 1 })
        expect(await survivingPersonIds()).toEqual([stale])

        await insertProgress(0, 9)
        await insertProgress(3, 4)

        expect(await sweeper.runOnce()).toMatchObject({ swept: 0, blocked: 1 })
        expect(await survivingPersonIds()).toEqual([stale])

        await query(`UPDATE cohort_membership_consumer_progress SET next_offset = 10 WHERE partition = 0`)

        expect(await sweeper.runOnce()).toMatchObject({ swept: 1, rowsDeleted: 1, blocked: 0 })
        expect(await survivingPersonIds()).toEqual([])
    })

    it('should delete only this cohort rows older than the run, and stop after one sweep', async () => {
        await readyRun()
        await openGate()

        const stale1 = await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)
        const stale2 = await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)
        const stale3 = await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)
        // A row written before the feature sorts below every producer stamp, so the run that did
        // not re-assert it deletes it. Those rows are most of what the first sweep has to remove.
        const preFeature = await insertMembership(TEAM_ID, COHORT_ID, UNVERSIONED)
        const asserted = await insertMembership(TEAM_ID, COHORT_ID, THRESHOLD)
        const liveChange = await insertMembership(TEAM_ID, COHORT_ID, ABOVE_THRESHOLD)
        const otherCohort = await insertMembership(TEAM_ID, COHORT_ID + 1, BELOW_THRESHOLD)
        const otherTeam = await insertMembership(TEAM_ID + 1, COHORT_ID, BELOW_THRESHOLD)

        expect(await sweeper.runOnce()).toMatchObject({ swept: 1, rowsDeleted: 4 })

        const surviving = await survivingPersonIds()
        expect(surviving).toEqual([asserted, liveChange, otherCohort, otherTeam].sort((a, b) => a.localeCompare(b)))
        expect(surviving).not.toEqual(expect.arrayContaining([stale1, stale2, stale3, preFeature]))
        expect(await readSweep()).toMatchObject({ status: 'swept', swept_rows: '4' })

        // A second cycle must not re-sweep a finished run.
        expect(await sweeper.runOnce()).toMatchObject({ swept: 0, rowsDeleted: 0 })
    })

    it.each([
        ['it never observed the snapshot it is supposed to have asserted', 'min_snapshot_version = NULL'],
        ['its watermark capture came back empty', `membership_hwms = '{}'::jsonb`],
        // Offsets from one feed prove nothing about another, so a run that outlived a broker
        // repoint or a topic change must not sweep on the watermarks it captured before it.
        ['its watermarks came from another cluster', `membership_cluster = 'moved-cluster'`],
        ['its watermarks came from another topic', `membership_topic = 'moved_topic'`],
    ])('should refuse to sweep a run when %s', async (_label, damage) => {
        watermarks = { 0: 10 }
        await readyRun()
        await insertProgress(0, 10)
        await query(`UPDATE cohort_membership_sweeps SET ${damage} WHERE run_id = $1`, [runId])

        const live = await insertMembership(TEAM_ID, COHORT_ID, ABOVE_THRESHOLD)
        const stale = await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)

        expect(await sweeper.runOnce()).toMatchObject({ swept: 0, rowsDeleted: 0 })
        expect(await survivingPersonIds()).toEqual([live, stale].sort((a, b) => a.localeCompare(b)))
    })

    it('should reclaim a sweep whose pod died mid-run', async () => {
        await readyRun()
        await openGate()
        const stale = await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)
        await query(
            `UPDATE cohort_membership_sweeps
             SET status = 'sweeping', claimed_at = CURRENT_TIMESTAMP - INTERVAL '1 hour'
             WHERE run_id = $1`,
            [runId]
        )

        expect(await sweeper.runOnce()).toMatchObject({ swept: 1, rowsDeleted: 1 })
        expect(await survivingPersonIds()).not.toContain(stale)
    })

    it('should yield a sweep whose claim was taken over mid-run', async () => {
        await readyRun()
        await openGate()
        await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)
        await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)
        const unreached = await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)

        // Take the claim over after the first delete page, as a reclaim after a stall would. The
        // heartbeat must notice and yield, instead of paging on and writing the terminal ledger
        // row over the new owner's state.
        const newOwnerToken = new UUIDT().toString()
        afterEachDeletePage(async (page) => {
            if (page === 1) {
                await query('UPDATE cohort_membership_sweeps SET claim_token = $1 WHERE run_id = $2', [
                    newOwnerToken,
                    runId,
                ])
            }
        })

        expect(await sweeper.runOnce()).toMatchObject({ rowsDeleted: 2 })
        expect(await survivingPersonIds()).toEqual([unreached])
        expect(await readSweep()).toMatchObject({ status: 'sweeping', swept_rows: null })
    })

    it('should send an interrupted sweep back to ready instead of retiring it', async () => {
        await readyRun()
        await openGate()
        await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)
        await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)
        const unreached = await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)

        // Shutdown lands between delete pages. Marking the run swept here would strand the rows
        // it never reached, because nothing revisits a swept run.
        afterEachDeletePage(() => {
            sweeper['stopping'] = true
        })

        expect(await sweeper.runOnce()).toMatchObject({ rowsDeleted: 2 })
        expect(await survivingPersonIds()).toEqual([unreached])
        expect(await readSweep()).toMatchObject({ status: 'ready', swept_rows: '2' })
    })

    it('should send a sweep whose rows were lock-skipped back to ready instead of retiring it', async () => {
        await readyRun()
        await openGate()
        const locked = await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)

        // A row another transaction holds locked is skipped by FOR UPDATE SKIP LOCKED, so the
        // delete page comes back empty while a stale row remains. Retiring the run as swept here
        // would strand that row, because nothing revisits a swept run.
        await postgres.transaction(PostgresUse.BEHAVIORAL_COHORTS_RW, 'holdRowLock', async (tx) => {
            await postgres.query(
                tx,
                'SELECT id FROM cohort_membership WHERE person_id = $1 FOR UPDATE',
                [locked],
                'lockStaleRow'
            )
            expect(await sweeper.runOnce()).toMatchObject({ swept: 1, rowsDeleted: 0 })
        })

        expect(await survivingPersonIds()).toEqual([locked])
        expect(await readSweep()).toMatchObject({ status: 'ready', swept_rows: '0' })

        // With the lock released, the next cycle finishes the run.
        expect(await sweeper.runOnce()).toMatchObject({ swept: 1, rowsDeleted: 1 })
        expect(await survivingPersonIds()).toEqual([])
        expect(await readSweep()).toMatchObject({ status: 'swept', swept_rows: '1' })
    })

    it('should abandon unproven and expired runs and collect aged garbage, sparing proven runs, even while watermark capture fails', async () => {
        await query(
            `INSERT INTO cohort_membership_sweeps (run_id, cohort_id, team_id, marker_bits, created_at, updated_at)
             VALUES ($1, $2, $3, 7, CURRENT_TIMESTAMP - INTERVAL '30 days',
                     CURRENT_TIMESTAMP - INTERVAL '30 days')`,
            [runId, COHORT_ID, TEAM_ID]
        )

        // A fully-proven run held back only by consumer lag must survive the short timeout: it
        // sweeps whenever the gate opens, and discarding it would leave the cohort stale.
        const blockedRunId = new UUIDT().toString()
        await query(
            `INSERT INTO cohort_membership_sweeps
                (run_id, cohort_id, team_id, marker_bits, min_marker_version, min_snapshot_version,
                 membership_hwms, status, ready_at, created_at, updated_at)
             VALUES ($1, $2, $3, -1, $4::timestamp, $5::timestamp, $6::jsonb, 'ready',
                     CURRENT_TIMESTAMP - INTERVAL '5 days', CURRENT_TIMESTAMP - INTERVAL '5 days',
                     CURRENT_TIMESTAMP - INTERVAL '5 days')`,
            [blockedRunId, COHORT_ID + 1, TEAM_ID, MARKER_VERSION, THRESHOLD, JSON.stringify({ 0: 10 })]
        )

        // A fully-marked run that promotion cannot ready, because watermark capture keeps
        // failing, is proven: the short timeout must not take it, and the failure must stay
        // contained to promotion so the abandonment below still runs in the same cycle. Only the
        // marker-retention horizon retires such a run.
        const unpromotedRunId = new UUIDT().toString()
        await query(
            `INSERT INTO cohort_membership_sweeps (run_id, cohort_id, team_id, marker_bits, created_at, updated_at)
             VALUES ($1, $2, $3, -1, CURRENT_TIMESTAMP - INTERVAL '5 days',
                     CURRENT_TIMESTAMP - INTERVAL '5 days')`,
            [unpromotedRunId, COHORT_ID + 2, TEAM_ID]
        )
        const expiredRunId = new UUIDT().toString()
        await query(
            `INSERT INTO cohort_membership_sweeps (run_id, cohort_id, team_id, marker_bits, created_at, updated_at)
             VALUES ($1, $2, $3, -1, CURRENT_TIMESTAMP - INTERVAL '31 days',
                     CURRENT_TIMESTAMP - INTERVAL '31 days')`,
            [expiredRunId, COHORT_ID + 3, TEAM_ID]
        )

        // GC hygiene rides the same cycle: a terminal ledger row and a progress row past the
        // marker-retention horizon are deleted, while recent rows survive. The progress bound is
        // the risky half: deleting a live partition's row would make the gate block every sweep.
        const gcRunId = new UUIDT().toString()
        await query(
            `INSERT INTO cohort_membership_sweeps
                (run_id, cohort_id, team_id, marker_bits, status, created_at, updated_at)
             VALUES ($1, $2, $3, -1, 'swept', CURRENT_TIMESTAMP - INTERVAL '31 days',
                     CURRENT_TIMESTAMP - INTERVAL '31 days')`,
            [gcRunId, COHORT_ID + 4, TEAM_ID]
        )
        await insertProgress(0, 5)
        await query(
            `INSERT INTO cohort_membership_consumer_progress (cluster, topic, partition, next_offset, updated_at)
             VALUES ($1, $2, 1, 5, CURRENT_TIMESTAMP - INTERVAL '31 days')`,
            [CLUSTER, TOPIC]
        )

        captureFailure = new Error('kafka down')

        expect(await sweeper.runOnce()).toMatchObject({ abandoned: 2 })
        expect(await readSweep()).toMatchObject({ status: 'abandoned' })

        expect(await query('SELECT 1 FROM cohort_membership_sweeps WHERE run_id = $1', [gcRunId])).toEqual([])
        expect(
            (await query<{ partition: number }>('SELECT partition FROM cohort_membership_consumer_progress')).map(
                (row) => row.partition
            )
        ).toEqual([0])

        const statuses = Object.fromEntries(
            (
                await query<{ run_id: string; status: string }>(
                    'SELECT run_id, status FROM cohort_membership_sweeps WHERE run_id = ANY($1)',
                    [[blockedRunId, unpromotedRunId, expiredRunId]]
                )
            ).map((row) => [row.run_id, row.status])
        )
        expect(statuses).toEqual({
            [blockedRunId]: 'ready',
            [unpromotedRunId]: 'collecting',
            [expiredRunId]: 'abandoned',
        })
    })
})
