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

    const config: CohortMembershipSweepConfig = {
        COHORT_MEMBERSHIP_SWEEP_INTERVAL_MS: 60000,
        // Small enough that the batched delete loop has to iterate.
        COHORT_MEMBERSHIP_SWEEP_BATCH_SIZE: 2,
        COHORT_MEMBERSHIP_SWEEP_CLAIM_TIMEOUT_MS: 300000,
        COHORT_MEMBERSHIP_SWEEP_ABANDON_AFTER_DAYS: 3,
    }

    let postgres: PostgresRouter
    let sweeper: CohortMembershipSweeper
    let watermarks: MembershipWatermarks
    let runId: string

    beforeEach(async () => {
        postgres = new PostgresRouter(defaultConfig)
        await resetBehavioralCohortsDatabase(postgres)
        watermarks = { 0: 10 }
        runId = new UUIDT().toString()
        sweeper = new CohortMembershipSweeper(config, postgres, {
            captureMembershipWatermarks: () => Promise.resolve(watermarks),
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
            `SELECT marker_bits, status, swept_rows, membership_hwms,
                    to_char(min_marker_version, 'YYYY-MM-DD HH24:MI:SS.US') AS min_marker_version
             FROM cohort_membership_sweeps WHERE run_id = $1 AND cohort_id = $2`,
            [runId, COHORT_ID]
        )
        return rows[0]
    }

    const insertMembership = async (teamId: number, cohortId: number, version: string | null): Promise<string> => {
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
                 membership_hwms, status)
             VALUES ($1, $2, $3, -1, $4::timestamp, $5::timestamp, $6::jsonb, 'ready')`,
            [runId, COHORT_ID, TEAM_ID, MARKER_VERSION, THRESHOLD, JSON.stringify(watermarks)]
        )
    }

    /** Record the consumer as having applied everything the run's watermarks cover. */
    const openGate = async (): Promise<void> => {
        for (const [partition, highWatermark] of Object.entries(watermarks)) {
            await query(`INSERT INTO cohort_membership_consumer_progress (partition, next_offset) VALUES ($1, $2)`, [
                Number(partition),
                highWatermark,
            ])
        }
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

        watermarks = { 0: 10, 3: 4 }
        // The last partition sets the sign bit, which is what completes the i64 bitmap.
        await sweeper.applyMarkers(
            sweeper.parseMarkers([markerMessage(COHORT_PARTITION_COUNT - 1, { last_updated: ABOVE_THRESHOLD })])
        )

        expect(await readSweep()).toMatchObject({
            marker_bits: '-1',
            status: 'ready',
            membership_hwms: { 0: 10, 3: 4 },
            min_marker_version: MARKER_VERSION,
        })
    })

    it('should hold the sweep until consumer progress passes every captured watermark', async () => {
        watermarks = { 0: 10, 3: 4 }
        await readyRun()
        const stale = await insertMembership(TEAM_ID, COHORT_ID, BELOW_THRESHOLD)

        expect(await sweeper.runOnce()).toMatchObject({ swept: 0, blocked: 1 })
        expect(await survivingPersonIds()).toEqual([stale])

        await query(`INSERT INTO cohort_membership_consumer_progress (partition, next_offset) VALUES (0, 9), (3, 4)`)

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
        const neverVersioned = await insertMembership(TEAM_ID, COHORT_ID, null)
        const asserted = await insertMembership(TEAM_ID, COHORT_ID, THRESHOLD)
        const liveChange = await insertMembership(TEAM_ID, COHORT_ID, ABOVE_THRESHOLD)
        const otherCohort = await insertMembership(TEAM_ID, COHORT_ID + 1, BELOW_THRESHOLD)
        const otherTeam = await insertMembership(TEAM_ID + 1, COHORT_ID, BELOW_THRESHOLD)

        expect(await sweeper.runOnce()).toMatchObject({ swept: 1, rowsDeleted: 3 })

        const surviving = await survivingPersonIds()
        expect(surviving).toEqual([asserted, liveChange, otherCohort, otherTeam].sort((a, b) => a.localeCompare(b)))
        expect(surviving).not.toEqual(expect.arrayContaining([stale1, stale2, neverVersioned]))
        expect(await readSweep()).toMatchObject({ status: 'swept', swept_rows: '3' })

        // A second cycle must not re-sweep a finished run.
        expect(await sweeper.runOnce()).toMatchObject({ swept: 0, rowsDeleted: 0 })
    })

    it.each([
        ['it never observed the snapshot it is supposed to have asserted', 'min_snapshot_version = NULL'],
        ['its watermark capture came back empty', `membership_hwms = '{}'::jsonb`],
    ])('should refuse to sweep a run when %s', async (_label, damage) => {
        watermarks = { 0: 10 }
        await readyRun()
        await query(`INSERT INTO cohort_membership_consumer_progress (partition, next_offset) VALUES (0, 10)`)
        await query(`UPDATE cohort_membership_sweeps SET ${damage} WHERE run_id = $1`, [runId])

        const live = await insertMembership(TEAM_ID, COHORT_ID, ABOVE_THRESHOLD)
        const unversioned = await insertMembership(TEAM_ID, COHORT_ID, null)

        expect(await sweeper.runOnce()).toMatchObject({ swept: 0, rowsDeleted: 0 })
        expect(await survivingPersonIds()).toEqual([live, unversioned].sort((a, b) => a.localeCompare(b)))
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

    it('should abandon a run whose marker set never completed', async () => {
        await query(
            `INSERT INTO cohort_membership_sweeps (run_id, cohort_id, team_id, marker_bits, created_at, updated_at)
             VALUES ($1, $2, $3, 7, CURRENT_TIMESTAMP - INTERVAL '30 days',
                     CURRENT_TIMESTAMP - INTERVAL '30 days')`,
            [runId, COHORT_ID, TEAM_ID]
        )

        expect(await sweeper.runOnce()).toMatchObject({ abandoned: 1 })
        expect(await readSweep()).toMatchObject({ status: 'abandoned' })
    })
})
