import { KAFKA_COHORT_MEMBERSHIP_CHANGED, KAFKA_COHORT_RECONCILE_MARKERS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { resetBehavioralCohortsDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { CdpCohortMembershipConsumer } from '../consumers/cdp-cohort-membership.consumer'
import { COHORT_PARTITION_COUNT } from '../services/cohort-membership/sweeper.service'

// Drives the whole chain against the running dev stack: real Kafka topics, the real membership
// consumer, the real marker consumer, and the real sweep loop. Lives under dev/ so CI skips it.
jest.setTimeout(180_000)

describe('cohort membership mark and sweep, end to end', () => {
    const TEAM_ID = 987654
    const COHORT_ID = 5150
    const SNAPSHOT_VERSION = '2026-08-26 10:00:00.000000'
    const STALE_VERSION = '2026-08-26 09:00:00.000000'

    let hub: Hub
    let consumer: CdpCohortMembershipConsumer
    let producer: KafkaProducerWrapper

    afterEach(async () => {
        await consumer?.stop()
        await producer?.disconnect()
        await closeHub(hub)
    })

    it('deletes rows the completed reconcile run did not re-assert', async () => {
        const runId = new UUIDT().toString()
        const stillMember = new UUIDT().toString()
        const droppedOut = new UUIDT().toString()

        hub = await createHub()
        await resetBehavioralCohortsDatabase(hub.postgres)

        // Someone who matched before the cohort was edited. No live transition ever arrives for
        // them, so without a sweep this row claims membership forever.
        await hub.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `INSERT INTO cohort_membership (team_id, cohort_id, person_id, in_cohort, version)
             VALUES ($1, $2, $3, true, $4::timestamp)`,
            [TEAM_ID, COHORT_ID, droppedOut, STALE_VERSION],
            'seedStaleRow'
        )

        consumer = new CdpCohortMembershipConsumer(
            {
                ...hub,
                COHORT_MEMBERSHIP_VERSION_WRITES_ENABLED: true,
                COHORT_MEMBERSHIP_SWEEP_ENABLED: true,
                COHORT_MEMBERSHIP_SWEEP_INTERVAL_MS: 1000,
            },
            createCdpConsumerDeps(hub)
        )
        await consumer.start()

        producer = await KafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)

        await producer.produce({
            topic: KAFKA_COHORT_MEMBERSHIP_CHANGED,
            key: Buffer.from(stillMember),
            value: Buffer.from(
                JSON.stringify({
                    team_id: TEAM_ID,
                    cohort_id: COHORT_ID,
                    person_id: stillMember,
                    last_updated: SNAPSHOT_VERSION,
                    status: 'entered',
                    origin: 'reconcile',
                    run_id: runId,
                })
            ),
        })
        await producer.flush()

        // The processor produces a marker only after its partition's membership rows are acked.
        await waitForExpect(async () => {
            const applied = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT person_id FROM cohort_membership WHERE person_id = $1',
                [stillMember],
                'awaitSnapshot'
            )
            expect(applied.rows).toHaveLength(1)
        }, 60_000)

        for (let partition = 0; partition < COHORT_PARTITION_COUNT; partition++) {
            await producer.produce({
                topic: KAFKA_COHORT_RECONCILE_MARKERS,
                key: Buffer.from(`${TEAM_ID}:${COHORT_ID}:${runId}:${partition}`),
                value: Buffer.from(
                    JSON.stringify({
                        type: 'reconcile_complete',
                        team_id: TEAM_ID,
                        cohort_id: COHORT_ID,
                        partition,
                        run_id: runId,
                        last_updated: SNAPSHOT_VERSION,
                    })
                ),
            })
        }
        await producer.flush()

        // Both checks sit in the same wait: the rows go before the ledger is marked done, so
        // asserting the ledger separately would race the sweep's own last statement.
        await waitForExpect(async () => {
            const members = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT person_id FROM cohort_membership WHERE team_id = $1 AND cohort_id = $2',
                [TEAM_ID, COHORT_ID],
                'readMembers'
            )
            expect(members.rows.map((row: { person_id: string }) => row.person_id)).toEqual([stillMember])

            const sweeps = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT marker_bits, status, swept_rows, snapshot_rows FROM cohort_membership_sweeps WHERE run_id = $1',
                [runId],
                'readSweep'
            )
            expect(sweeps.rows[0]).toMatchObject({
                marker_bits: '-1',
                status: 'swept',
                swept_rows: '1',
                snapshot_rows: '1',
            })
        }, 120_000)
    })
})
