import { Message } from 'node-rdkafka'

import { resetKafka } from '~/tests/helpers/kafka'
import { UUIDT } from '~/utils/utils'

import { resetBehavioralCohortsDatabase } from '../../../tests/helpers/sql'
import { KAFKA_COHORT_MEMBERSHIP_CHANGED } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { PostgresUse } from '../../utils/db/postgres'
import { createCohortMembershipEvent, createCohortMembershipEvents, createKafkaMessage } from '../_tests/fixtures'
import { CdpCohortMembershipConsumer } from './cdp-cohort-membership.consumer'

jest.setTimeout(20_000)

describe('CdpCohortMembershipConsumer', () => {
    let hub: Hub
    let consumer: CdpCohortMembershipConsumer

    beforeEach(async () => {
        await resetKafka()
        hub = await createHub()
        consumer = new CdpCohortMembershipConsumer(hub)
        await resetBehavioralCohortsDatabase(hub.postgres)
    })

    afterEach(async () => {
        await consumer.stop()
        await closeHub(hub)
    })

    describe('end-to-end cohort membership processing', () => {
        const personId1 = new UUIDT().toString()
        const personId2 = new UUIDT().toString()
        const personId3 = new UUIDT().toString()
        it('should process entered and left events and write to PostgreSQL correctly', async () => {
            // Test data using helper functions
            const testEvents = createCohortMembershipEvents([
                {
                    personId: personId1,
                    cohortId: 456,
                    teamId: 1,
                    cohort_membership_changed: 'entered',
                },
                {
                    personId: personId2,
                    cohortId: 456,
                    teamId: 1,
                    cohort_membership_changed: 'entered',
                },
                {
                    personId: personId3,
                    cohortId: 457,
                    teamId: 1,
                    cohort_membership_changed: 'left',
                },
            ])

            // Create mock Kafka messages
            const messages = testEvents.map((event, index) =>
                createKafkaMessage(event, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: index })
            )

            // Process the batch of messages
            await (consumer as any).handleBatch(messages)

            // Verify data was written to PostgreSQL
            const result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1 ORDER BY person_id, cohort_id',
                [1],
                'testQuery'
            )

            expect(result.rows).toHaveLength(3)

            // Verify first entered event
            expect(result.rows[0]).toMatchObject({
                team_id: '1',
                cohort_id: '456',
                person_id: personId1,
                in_cohort: true,
            })

            // Verify second entered event
            expect(result.rows[1]).toMatchObject({
                team_id: '1',
                cohort_id: '456',
                person_id: personId2,
                in_cohort: true,
            })

            // Verify left event
            expect(result.rows[2]).toMatchObject({
                team_id: '1',
                cohort_id: '457',
                person_id: personId3,
                in_cohort: false,
            })
        })

        it('should handle complete person lifecycle: enter -> leave -> re-enter cohort', async () => {
            // Step 1: Person enters the cohort for the first time
            const enterEvent = createCohortMembershipEvent({
                personId: personId1,
                cohortId: 456,
                teamId: 1,
                cohort_membership_changed: 'entered',
            })

            await (consumer as any).handleBatch([
                createKafkaMessage(enterEvent, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }),
            ])

            let result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1 AND person_id = $2 AND cohort_id = $3',
                [1, personId1, 456],
                'testQuery'
            )

            expect(result.rows[0].in_cohort).toBe(true)
            const firstTimestamp = result.rows[0].last_updated

            // Wait to ensure timestamp difference
            await new Promise((resolve) => setTimeout(resolve, 10))

            // Step 2: Person leaves the cohort
            const leaveEvent = createCohortMembershipEvent({
                personId: personId1,
                cohortId: 456,
                teamId: 1,
                cohort_membership_changed: 'left',
            })

            await (consumer as any).handleBatch([
                createKafkaMessage(leaveEvent, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 1 }),
            ])

            result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1 AND person_id = $2 AND cohort_id = $3',
                [1, personId1, 456],
                'testQuery'
            )

            expect(result.rows).toHaveLength(1) // Same record, just updated
            expect(result.rows[0].in_cohort).toBe(false)
            const secondTimestamp = result.rows[0].last_updated
            expect(new Date(secondTimestamp).getTime()).toBeGreaterThan(new Date(firstTimestamp).getTime())

            // Wait to ensure timestamp difference
            await new Promise((resolve) => setTimeout(resolve, 10))

            // Step 3: Person re-enters the cohort
            const reEnterEvent = createCohortMembershipEvent({
                personId: personId1,
                cohortId: 456,
                teamId: 1,
                cohort_membership_changed: 'entered',
            })

            await (consumer as any).handleBatch([
                createKafkaMessage(reEnterEvent, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 2 }),
            ])

            result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1 AND person_id = $2 AND cohort_id = $3',
                [1, personId1, 456],
                'testQuery'
            )

            expect(result.rows).toHaveLength(1) // Still same record, just updated again
            expect(result.rows[0].in_cohort).toBe(true) // Back in the cohort
            const thirdTimestamp = result.rows[0].last_updated
            expect(new Date(thirdTimestamp).getTime()).toBeGreaterThan(new Date(secondTimestamp).getTime())
        })

        it('should reject entire batch when invalid messages are present', async () => {
            const validEvent = {
                personId: personId1,
                cohortId: 456,
                teamId: 1,
                cohort_membership_changed: 'entered',
            }

            const messages: Message[] = [
                // Valid message
                createKafkaMessage(validEvent, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }),
                // Invalid JSON (manually create this one since it's intentionally malformed)
                {
                    value: Buffer.from('invalid json'),
                    topic: KAFKA_COHORT_MEMBERSHIP_CHANGED,
                    partition: 0,
                    offset: 1,
                    timestamp: Date.now(),
                    key: null,
                    size: 0,
                },
                // Missing required fields
                createKafkaMessage({ personId: 124 }, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 2 }),
                // Empty message (manually create this one since it has null value)
                {
                    value: null,
                    topic: KAFKA_COHORT_MEMBERSHIP_CHANGED,
                    partition: 0,
                    offset: 3,
                    timestamp: Date.now(),
                    key: null,
                    size: 0,
                },
            ]

            // Should throw due to invalid messages in batch
            await expect((consumer as any).handleBatch(messages)).rejects.toThrow()

            // Verify NO data was inserted
            const result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1',
                [1],
                'testQuery'
            )

            expect(result.rows).toHaveLength(0) // No data should be inserted
        })
    })
})
