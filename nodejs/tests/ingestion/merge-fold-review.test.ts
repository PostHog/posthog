import { DateTime } from 'luxon'

import { createHogTransformerService } from '~/cdp/hog-transformations/hog-transformer.service'
import { ClickhouseGroupRepository } from '~/common/groups/repositories/clickhouse-group-repository'
import { UUIDT } from '~/common/utils/utils'
import { IngestionConsumer } from '~/ingestion/ingestion-consumer'
import { createAiEventSubpipeline } from '~/ingestion/pipelines/ai'
import { Clickhouse } from '~/tests/helpers/clickhouse'
import { waitForExpect } from '~/tests/helpers/expectations'
import {
    EventBuilder,
    createKafkaMessages,
    createTestWithTeamIngester,
    fetchEvents,
    waitForClickHouseKafkaConsumer,
    waitForKafkaMessages,
} from '~/tests/helpers/ingestion-e2e'
import { createTestIngestionOutputs, createTestMonitoringOutputs } from '~/tests/helpers/ingestion-outputs'
import { TEST_KAFKA_TOPICS, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { fetchPostgresPersons, resetTestDatabase } from '~/tests/helpers/sql'

jest.mock('~/common/utils/logger')

// Review diagnostic for PR #72823 (merge folding).
// Every assertion below encodes today's SEQUENTIAL per-event semantics for
// person property snapshots on emitted events. Running this file with
// PERSON_MERGE_FOLD_ENABLED=true shows exactly where folding diverges.
describe.each([
    { PERSONS_PREFETCH_ENABLED: true, PERSON_MERGE_FOLD_ENABLED: false },
    { PERSONS_PREFETCH_ENABLED: true, PERSON_MERGE_FOLD_ENABLED: true },
])('Merge fold per-event snapshot semantics (fold=$PERSON_MERGE_FOLD_ENABLED)', (pipelineConfig) => {
    const testWithTeamIngester = createTestWithTeamIngester(pipelineConfig, (infra, kafkaProducer) => {
        const outputs = createTestIngestionOutputs(kafkaProducer)
        return new IngestionConsumer(infra.config, {
            postgres: infra.postgres,
            redisPool: infra.redisPool,
            teamManager: infra.teamManager,
            groupTypeManager: infra.groupTypeManager,
            groupRepository: infra.groupRepository,
            personRepository: infra.personRepository,
            cookielessManager: infra.cookielessManager,
            outputs,
            clickhouseGroupRepository: new ClickhouseGroupRepository(outputs),
            aiSubpipelineFactory: createAiEventSubpipeline,
            hogTransformer: createHogTransformerService(infra.config, {
                geoipService: infra.geoipService,
                postgres: infra.postgres,
                pubSub: infra.pubSub,
                encryptedFields: infra.encryptedFields,
                integrationManager: infra.integrationManager,
                monitoringOutputs: createTestMonitoringOutputs(kafkaProducer),
                teamManager: infra.teamManager,
            }),
        })
    })

    let clickhouse: Clickhouse
    beforeAll(async () => {
        clickhouse = Clickhouse.create()
        await ensureKafkaTopics(TEST_KAFKA_TOPICS)
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        await waitForClickHouseKafkaConsumer(clickhouse)
        process.env.SITE_URL = 'https://example.com'
    })

    afterAll(async () => {
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        clickhouse.close()
    })

    async function seedAnonPersons(
        ingester: IngestionConsumer,
        team: any,
        token: string,
        kafkaProducer: any,
        anonA: string,
        anonB: string,
        timestamp: number
    ) {
        await ingester.handleKafkaBatch(
            createKafkaMessages(
                [
                    new EventBuilder(team, anonA)
                        .withEvent('seed a')
                        .withProperties({ $set: { from_a: true } })
                        .withTimestamp(timestamp)
                        .build(),
                    new EventBuilder(team, anonB)
                        .withEvent('seed b')
                        .withProperties({ $set: { from_b: true } })
                        .withTimestamp(timestamp)
                        .build(),
                ],
                token
            )
        )
        await waitForKafkaMessages(kafkaProducer)
    }

    testWithTeamIngester(
        'interleaved: $identify(A), middle event, $identify(B) — middle event must not see B profile',
        {},
        async ({ ingester, infra, team, kafkaProducer, token }) => {
            const userId = `user-${new UUIDT().toString()}`
            const anonA = `anon-a-${userId}`
            const anonB = `anon-b-${userId}`
            const ts = DateTime.now().toMillis()

            await seedAnonPersons(ingester, team, token, kafkaProducer, anonA, anonB, ts)

            await ingester.handleKafkaBatch(
                createKafkaMessages(
                    [
                        new EventBuilder(team, userId)
                            .withEvent('$identify')
                            .withProperties({ $anon_distinct_id: anonA, $set: { i1: true } })
                            .withTimestamp(ts + 10)
                            .build(),
                        new EventBuilder(team, userId)
                            .withEvent('middle event')
                            .withTimestamp(ts + 20)
                            .build(),
                        new EventBuilder(team, userId)
                            .withEvent('$identify')
                            .withProperties({ $anon_distinct_id: anonB, $set: { i2: true } })
                            .withTimestamp(ts + 30)
                            .build(),
                    ],
                    token
                )
            )
            await waitForKafkaMessages(kafkaProducer)

            await waitForExpect(async () => {
                const events = await fetchEvents(clickhouse, team.id)
                expect(events.length).toBe(5)
            })

            const events = await fetchEvents(clickhouse, team.id)
            const identify1 = events.find((e) => e.event === '$identify' && e.properties.$anon_distinct_id === anonA)!
            const middle = events.find((e) => e.event === 'middle event')!
            const identify2 = events.find((e) => e.event === '$identify' && e.properties.$anon_distinct_id === anonB)!

            // Sequential semantics: A's profile lands at identify1, B's only at identify2.
            expect(identify1.person_properties).toEqual(expect.objectContaining({ from_a: true, i1: true }))
            expect(identify1.person_properties).not.toHaveProperty('from_b')
            expect(identify1.person_properties).not.toHaveProperty('i2')

            expect(middle.person_properties).toEqual(expect.objectContaining({ from_a: true, i1: true }))
            expect(middle.person_properties).not.toHaveProperty('from_b')

            expect(identify2.person_properties).toEqual(
                expect.objectContaining({ from_a: true, from_b: true, i1: true, i2: true })
            )

            // Final person state is the same either way.
            const persons = await fetchPostgresPersons(infra.postgres, team.id)
            expect(persons).toHaveLength(1)
        }
    )

    testWithTeamIngester(
        'consecutive: $identify(A), $identify(B), after event — first identify must not see B profile',
        {},
        async ({ ingester, infra, team, kafkaProducer, token }) => {
            const userId = `user-${new UUIDT().toString()}`
            const anonA = `anon-a-${userId}`
            const anonB = `anon-b-${userId}`
            const ts = DateTime.now().toMillis()

            await seedAnonPersons(ingester, team, token, kafkaProducer, anonA, anonB, ts)

            await ingester.handleKafkaBatch(
                createKafkaMessages(
                    [
                        new EventBuilder(team, userId)
                            .withEvent('$identify')
                            .withProperties({ $anon_distinct_id: anonA, $set: { i1: true } })
                            .withTimestamp(ts + 10)
                            .build(),
                        new EventBuilder(team, userId)
                            .withEvent('$identify')
                            .withProperties({ $anon_distinct_id: anonB, $set: { i2: true } })
                            .withTimestamp(ts + 20)
                            .build(),
                        new EventBuilder(team, userId)
                            .withEvent('after event')
                            .withTimestamp(ts + 30)
                            .build(),
                    ],
                    token
                )
            )
            await waitForKafkaMessages(kafkaProducer)

            await waitForExpect(async () => {
                const events = await fetchEvents(clickhouse, team.id)
                expect(events.length).toBe(5)
            })

            const events = await fetchEvents(clickhouse, team.id)
            const identify1 = events.find((e) => e.event === '$identify' && e.properties.$anon_distinct_id === anonA)!
            const identify2 = events.find((e) => e.event === '$identify' && e.properties.$anon_distinct_id === anonB)!
            const after = events.find((e) => e.event === 'after event')!

            console.log('[fold-review] consecutive snapshots', {
                identify1: identify1.person_properties,
                identify2: identify2.person_properties,
                after: after.person_properties,
            })

            // Sequential semantics: identify1's snapshot has A's profile but NOT B's.
            expect(identify1.person_properties).toEqual(expect.objectContaining({ from_a: true, i1: true }))
            expect(identify1.person_properties).not.toHaveProperty('from_b')
            expect(identify1.person_properties).not.toHaveProperty('i2')

            expect(identify2.person_properties).toEqual(
                expect.objectContaining({ from_a: true, from_b: true, i1: true, i2: true })
            )
            expect(after.person_properties).toEqual(
                expect.objectContaining({ from_a: true, from_b: true, i1: true, i2: true })
            )

            // Final person state must be identical regardless of folding.
            const persons = await fetchPostgresPersons(infra.postgres, team.id)
            expect(persons).toHaveLength(1)
            expect(persons[0].properties).toEqual(
                expect.objectContaining({ from_a: true, from_b: true, i1: true, i2: true })
            )
            expect(persons[0].is_identified).toBe(true)
        }
    )
})
