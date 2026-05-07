import { Message } from 'node-rdkafka'

import { resetKafka } from '~/tests/helpers/kafka'
import { UUIDT } from '~/utils/utils'

import { createCdpConsumerDeps } from '../../../tests/helpers/cdp'
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
        consumer = new CdpCohortMembershipConsumer(hub, createCdpConsumerDeps(hub))
        await consumer.start()
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
            const testEvents = createCohortMembershipEvents([
                {
                    person_id: personId1,
                    cohort_id: 456,
                    team_id: 1,
                    status: 'entered',
                },
                {
                    person_id: personId2,
                    cohort_id: 456,
                    team_id: 1,
                    status: 'entered',
                },
                {
                    person_id: personId3,
                    cohort_id: 457,
                    team_id: 1,
                    status: 'left',
                },
            ])

            const messages = testEvents.map((event, index) =>
                createKafkaMessage(event, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: index })
            )

            const cohortMembershipChanges = consumer['_parseAndValidateBatch'](messages)
            await consumer['persistCohortMembershipChanges'](cohortMembershipChanges)

            const result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1 ORDER BY person_id, cohort_id',
                [1],
                'testQuery'
            )

            expect(result.rows).toHaveLength(3)

            expect(result.rows[0]).toMatchObject({
                team_id: '1',
                cohort_id: '456',
                person_id: personId1,
                in_cohort: true,
            })

            expect(result.rows[1]).toMatchObject({
                team_id: '1',
                cohort_id: '456',
                person_id: personId2,
                in_cohort: true,
            })

            expect(result.rows[2]).toMatchObject({
                team_id: '1',
                cohort_id: '457',
                person_id: personId3,
                in_cohort: false,
            })
        })

        it('should handle complete person lifecycle: enter -> leave -> re-enter cohort', async () => {
            // Step 1: Person enters the cohort
            const enterEvent = createCohortMembershipEvent({
                person_id: personId1,
                cohort_id: 456,
                team_id: 1,
                status: 'entered',
            })

            const enterMessages = [
                createKafkaMessage(enterEvent, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }),
            ]
            const enterChanges = consumer['_parseAndValidateBatch'](enterMessages)
            await consumer['persistCohortMembershipChanges'](enterChanges)

            let result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1 AND person_id = $2 AND cohort_id = $3',
                [1, personId1, 456],
                'testQuery'
            )

            expect(result.rows[0].in_cohort).toBe(true)
            const firstTimestamp = result.rows[0].last_updated

            await new Promise((resolve) => setTimeout(resolve, 10))

            // Step 2: Person leaves the cohort
            const leaveEvent = createCohortMembershipEvent({
                person_id: personId1,
                cohort_id: 456,
                team_id: 1,
                status: 'left',
            })

            const leaveMessages = [
                createKafkaMessage(leaveEvent, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 1 }),
            ]
            const leaveChanges = consumer['_parseAndValidateBatch'](leaveMessages)
            await consumer['persistCohortMembershipChanges'](leaveChanges)

            result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1 AND person_id = $2 AND cohort_id = $3',
                [1, personId1, 456],
                'testQuery'
            )

            expect(result.rows).toHaveLength(1)
            expect(result.rows[0].in_cohort).toBe(false)
            const secondTimestamp = result.rows[0].last_updated
            expect(new Date(secondTimestamp).getTime()).toBeGreaterThan(new Date(firstTimestamp).getTime())

            await new Promise((resolve) => setTimeout(resolve, 10))

            // Step 3: Person re-enters the cohort
            const reEnterEvent = createCohortMembershipEvent({
                person_id: personId1,
                cohort_id: 456,
                team_id: 1,
                status: 'entered',
            })

            const reEnterMessages = [
                createKafkaMessage(reEnterEvent, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 2 }),
            ]
            const reEnterChanges = consumer['_parseAndValidateBatch'](reEnterMessages)
            await consumer['persistCohortMembershipChanges'](reEnterChanges)

            result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1 AND person_id = $2 AND cohort_id = $3',
                [1, personId1, 456],
                'testQuery'
            )

            expect(result.rows).toHaveLength(1)
            expect(result.rows[0].in_cohort).toBe(true)
            const thirdTimestamp = result.rows[0].last_updated
            expect(new Date(thirdTimestamp).getTime()).toBeGreaterThan(new Date(secondTimestamp).getTime())
        })

        it('should deduplicate batch entries for the same (team_id, cohort_id, person_id), keeping last in Kafka order', async () => {
            const testEvents = createCohortMembershipEvents([
                {
                    person_id: personId1,
                    cohort_id: 456,
                    team_id: 1,
                    status: 'entered',
                },
                {
                    person_id: personId1,
                    cohort_id: 456,
                    team_id: 1,
                    status: 'left',
                },
            ])

            const messages = testEvents.map((event, index) =>
                createKafkaMessage(event, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: index })
            )

            const cohortMembershipChanges = consumer['_parseAndValidateBatch'](messages)
            await consumer['persistCohortMembershipChanges'](cohortMembershipChanges)

            const result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1 AND person_id = $2 AND cohort_id = $3',
                [1, personId1, 456],
                'testQuery'
            )

            expect(result.rows).toHaveLength(1)
            expect(result.rows[0].in_cohort).toBe(false)
        })

        it('should reject entire batch when invalid messages are present', async () => {
            const validEvent = {
                person_id: personId1,
                cohort_id: 456,
                team_id: 1,
                status: 'entered',
            }

            const messages: Message[] = [
                createKafkaMessage(validEvent, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 0 }),
                {
                    value: Buffer.from('invalid json'),
                    topic: KAFKA_COHORT_MEMBERSHIP_CHANGED,
                    partition: 0,
                    offset: 1,
                    timestamp: Date.now(),
                    key: null,
                    size: 0,
                },
                createKafkaMessage({ person_id: 124 }, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: 2 }),
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

            expect(() => consumer['_parseAndValidateBatch'](messages)).toThrow()

            const result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1',
                [1],
                'testQuery'
            )

            expect(result.rows).toHaveLength(0)
        })

        it('should not produce side effects when database insertion fails', async () => {
            const testEvents = createCohortMembershipEvents([
                {
                    person_id: personId1,
                    cohort_id: 456,
                    team_id: 1,
                    status: 'entered',
                },
                {
                    person_id: personId2,
                    cohort_id: 456,
                    team_id: 1,
                    status: 'entered',
                },
            ])

            const messages = testEvents.map((event, index) =>
                createKafkaMessage(event, { topic: KAFKA_COHORT_MEMBERSHIP_CHANGED, offset: index })
            )

            const cohortMembershipChanges = consumer['_parseAndValidateBatch'](messages)

            const originalQuery = hub.postgres.query.bind(hub.postgres)
            hub.postgres.query = jest.fn().mockRejectedValue(new Error('Database connection failed'))

            await expect(consumer['persistCohortMembershipChanges'](cohortMembershipChanges)).rejects.toThrow(
                'Database connection failed'
            )

            hub.postgres.query = originalQuery

            const result = await hub.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'SELECT * FROM cohort_membership WHERE team_id = $1',
                [1],
                'testQuery'
            )
            expect(result.rows).toHaveLength(0)
        })
    })
})
