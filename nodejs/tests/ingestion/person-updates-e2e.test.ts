/**
 * Person Updates E2E Tests
 *
 * This test suite verifies that person creation and updates work correctly
 * across all combinations of configuration flags:
 *
 * - PERSON_BATCH_WRITING_DB_WRITE_MODE: 'NO_ASSERT' | 'ASSERT_VERSION'
 * - PERSON_BATCH_WRITING_USE_BATCH_UPDATES: true | false (only applies to NO_ASSERT)
 * - PERSONS_PREFETCH_ENABLED: true | false
 *
 * The goal is to ensure basic person operations work correctly regardless of
 * which flag combination is used, catching regressions early.
 */
import { DateTime } from 'luxon'

import { createHogTransformerService } from '~/cdp/hog-transformations/hog-transformer.service'
import { ClickhouseGroupRepository } from '~/common/groups/repositories/clickhouse-group-repository'
import { UUIDT } from '~/common/utils/utils'
import { PersonBatchWritingDbWriteMode } from '~/ingestion/config'
import { IngestionConsumer } from '~/ingestion/ingestion-consumer'
import { waitForExpect } from '~/tests/helpers/expectations'
import {
    EventBuilder,
    createKafkaMessages,
    createTestWithTeamIngester,
    ensureIngestionE2EInfraReady,
    waitForKafkaMessages,
} from '~/tests/helpers/ingestion-e2e'
import { createTestIngestionOutputs, createTestMonitoringOutputs } from '~/tests/helpers/ingestion-outputs'

jest.mock('~/common/utils/token-bucket', () => {
    const mockConsume = jest.fn().mockReturnValue(true)
    return {
        IngestionWarningLimiter: {
            consume: mockConsume,
        },
    }
})

jest.mock('~/common/utils/logger')

// All possible values for each flag
const DB_WRITE_MODES: PersonBatchWritingDbWriteMode[] = ['NO_ASSERT', 'ASSERT_VERSION']
const USE_BATCH_UPDATES_OPTIONS = [true, false]
const PREFETCH_OPTIONS = [true, false]

interface PersonUpdateConfig {
    PERSON_BATCH_WRITING_DB_WRITE_MODE: PersonBatchWritingDbWriteMode
    PERSON_BATCH_WRITING_USE_BATCH_UPDATES: boolean
    PERSONS_PREFETCH_ENABLED: boolean
}

// Generate all combinations of all flags
const FLAG_COMBINATIONS: PersonUpdateConfig[] = DB_WRITE_MODES.flatMap((dbWriteMode) =>
    USE_BATCH_UPDATES_OPTIONS.flatMap((useBatchUpdates) =>
        PREFETCH_OPTIONS.map((prefetch) => ({
            PERSON_BATCH_WRITING_DB_WRITE_MODE: dbWriteMode,
            PERSON_BATCH_WRITING_USE_BATCH_UPDATES: useBatchUpdates,
            PERSONS_PREFETCH_ENABLED: prefetch,
        }))
    )
)

const formatConfigName = (config: PersonUpdateConfig): string => {
    const mode = config.PERSON_BATCH_WRITING_DB_WRITE_MODE
    const batch = config.PERSON_BATCH_WRITING_USE_BATCH_UPDATES ? 'batch' : 'individual'
    const prefetch = config.PERSONS_PREFETCH_ENABLED ? 'prefetch' : 'no-prefetch'
    return `${mode}, ${batch}, ${prefetch}`
}

describe.each(FLAG_COMBINATIONS)('Person Updates E2E ($#)', (config) => {
    const configName = formatConfigName(config)
    const testWithTeamIngester = createTestWithTeamIngester(config, (infra, kafkaProducer) => {
        const outputs = createTestIngestionOutputs(kafkaProducer)
        return new IngestionConsumer(infra.config, {
            postgres: infra.postgres,
            redisPool: infra.redisPool,
            teamManager: infra.teamManager,
            groupTypeManager: infra.groupTypeManager,
            groupRepository: infra.groupRepository,
            personRepository: infra.personRepository,
            cookielessManager: infra.cookielessManager,
            hogTransformer: createHogTransformerService(infra.config, {
                geoipService: infra.geoipService,
                postgres: infra.postgres,
                pubSub: infra.pubSub,
                encryptedFields: infra.encryptedFields,
                integrationManager: infra.integrationManager,
                monitoringOutputs: createTestMonitoringOutputs(kafkaProducer),
            }),
            outputs,
            clickhouseGroupRepository: new ClickhouseGroupRepository(outputs),
        })
    })
    const lastSeenAtEnabled = { teamOverrides: { extra_settings: { person_last_seen_at_enabled: true } } }

    beforeAll(async () => {
        await ensureIngestionE2EInfraReady()
    })

    describe(configName, () => {
        testWithTeamIngester(
            'should create a new person on first event',
            lastSeenAtEnabled,
            async ({ infra, team, kafkaProducer, ingester, token }) => {
                const distinctId = new UUIDT().toString()

                await ingester.handleKafkaBatch(
                    createKafkaMessages([new EventBuilder(team, distinctId).withEvent('test_event').build()], token)
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    expect(person!.team_id).toBe(team.id)
                    // last_seen_at should be set to an hour-rounded timestamp
                    expect(person!.last_seen_at).toBeDefined()
                    expect(person!.last_seen_at!.minute).toBe(0)
                    expect(person!.last_seen_at!.second).toBe(0)
                    expect(person!.last_seen_at!.millisecond).toBe(0)
                })
            }
        )

        testWithTeamIngester(
            'should set person properties with $identify and $set',
            lastSeenAtEnabled,
            async ({ infra, team, kafkaProducer, ingester, token }) => {
                const distinctId = new UUIDT().toString()
                const timestamp = DateTime.now().toMillis()
                const expectedLastSeenAt = DateTime.fromMillis(timestamp).startOf('hour')

                // Create person with initial properties
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({
                                    $set: { name: 'Initial Name', email: 'test@example.com' },
                                })
                                .withTimestamp(timestamp)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    expect(person!.properties).toEqual(
                        expect.objectContaining({
                            name: 'Initial Name',
                            email: 'test@example.com',
                        })
                    )
                    // last_seen_at should be set to the hour-rounded event timestamp
                    expect(person!.last_seen_at).toBeDefined()
                    expect(person!.last_seen_at!.toMillis()).toBe(expectedLastSeenAt.toMillis())
                })
            }
        )

        testWithTeamIngester(
            'should update person properties across multiple events in same batch',
            lastSeenAtEnabled,
            async ({ infra, team, kafkaProducer, ingester, token }) => {
                const distinctId = new UUIDT().toString()
                const timestamp = DateTime.now().toMillis()

                // Send multiple events in a single batch
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({
                                    $set: { prop1: 'value1' },
                                })
                                .withTimestamp(timestamp)
                                .build(),
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({
                                    $set: { prop2: 'value2' },
                                })
                                .withTimestamp(timestamp + 1)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    expect(person!.properties).toEqual(
                        expect.objectContaining({
                            prop1: 'value1',
                            prop2: 'value2',
                        })
                    )
                })
            }
        )

        testWithTeamIngester(
            'should update person properties across multiple batches',
            lastSeenAtEnabled,
            async ({ infra, team, kafkaProducer, ingester, token }) => {
                const distinctId = new UUIDT().toString()
                const timestamp = DateTime.now().toMillis()

                // First batch: create person
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({
                                    $set: { initial_prop: 'initial_value' },
                                })
                                .withTimestamp(timestamp)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                // Wait for person to be created
                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    expect(person!.properties).toEqual(
                        expect.objectContaining({
                            initial_prop: 'initial_value',
                        })
                    )
                })

                // Second batch: update person
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({
                                    $set: { new_prop: 'new_value', updated_prop: 'updated' },
                                })
                                .withTimestamp(timestamp + 1000)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    expect(person!.properties).toEqual(
                        expect.objectContaining({
                            initial_prop: 'initial_value',
                            new_prop: 'new_value',
                            updated_prop: 'updated',
                        })
                    )
                })
            }
        )

        testWithTeamIngester(
            'should handle $set_once correctly',
            lastSeenAtEnabled,
            async ({ infra, team, kafkaProducer, ingester, token }) => {
                const distinctId = new UUIDT().toString()
                const timestamp = DateTime.now().toMillis()

                // First event sets initial value
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({
                                    $set_once: { first_seen: 'original_value' },
                                })
                                .withTimestamp(timestamp)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    expect(person!.properties).toEqual(
                        expect.objectContaining({
                            first_seen: 'original_value',
                        })
                    )
                })

                // Second event tries to overwrite with $set_once - should be ignored
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({
                                    $set_once: { first_seen: 'should_be_ignored' },
                                })
                                .withTimestamp(timestamp + 1000)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    // Value should remain unchanged
                    expect(person!.properties.first_seen).toBe('original_value')
                })
            }
        )

        testWithTeamIngester(
            'should handle $unset correctly',
            lastSeenAtEnabled,
            async ({ infra, team, kafkaProducer, ingester, token }) => {
                const distinctId = new UUIDT().toString()
                const timestamp = DateTime.now().toMillis()

                // Create person with properties
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({
                                    $set: { keep_prop: 'keep', remove_prop: 'remove' },
                                })
                                .withTimestamp(timestamp)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    expect(person!.properties).toHaveProperty('remove_prop')
                })

                // Unset a property
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({
                                    $unset: ['remove_prop'],
                                })
                                .withTimestamp(timestamp + 1000)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    expect(person!.properties).toEqual(
                        expect.objectContaining({
                            keep_prop: 'keep',
                        })
                    )
                    expect(person!.properties).not.toHaveProperty('remove_prop')
                })
            }
        )

        testWithTeamIngester(
            'should handle combined $set and $unset in same event',
            lastSeenAtEnabled,
            async ({ infra, team, kafkaProducer, ingester, token }) => {
                const distinctId = new UUIDT().toString()
                const timestamp = DateTime.now().toMillis()

                // Create person with initial properties
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({
                                    $set: { prop1: 'value1', prop2: 'value2', prop3: 'value3' },
                                })
                                .withTimestamp(timestamp)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                // Update with combined $set and $unset
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({
                                    $set: { prop1: 'updated_value1', prop4: 'value4' },
                                    $unset: ['prop2'],
                                })
                                .withTimestamp(timestamp + 1000)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    expect(person!.properties).toEqual(
                        expect.objectContaining({
                            prop1: 'updated_value1',
                            prop3: 'value3',
                            prop4: 'value4',
                        })
                    )
                    expect(person!.properties).not.toHaveProperty('prop2')
                })
            }
        )

        testWithTeamIngester(
            'should update last_seen_at when event timestamp is in a newer hour',
            lastSeenAtEnabled,
            async ({ infra, team, kafkaProducer, ingester, token }) => {
                const distinctId = new UUIDT().toString()
                // Start at the beginning of an hour to make assertions clearer
                const baseTime = DateTime.now().startOf('hour')
                const firstTimestamp = baseTime.toMillis()
                const secondTimestamp = baseTime.plus({ hours: 2 }).toMillis()

                // First event creates the person
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({ $set: { initial: true } })
                                .withTimestamp(firstTimestamp)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    expect(person!.last_seen_at).toBeDefined()
                    expect(person!.last_seen_at!.toMillis()).toBe(baseTime.toMillis())
                })

                // Second event 2 hours later should update last_seen_at
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('pageview')
                                .withTimestamp(secondTimestamp)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    expect(person!.last_seen_at).toBeDefined()
                    expect(person!.last_seen_at!.toMillis()).toBe(baseTime.plus({ hours: 2 }).toMillis())
                })
            }
        )

        testWithTeamIngester(
            'should not update last_seen_at when $update_person_last_seen_at is false',
            lastSeenAtEnabled,
            async ({ infra, team, kafkaProducer, ingester, token }) => {
                const distinctId = new UUIDT().toString()
                const baseTime = DateTime.now().startOf('hour')
                const firstTimestamp = baseTime.toMillis()
                const secondTimestamp = baseTime.plus({ hours: 2 }).toMillis()

                // First event creates the person
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({ $set: { initial: true } })
                                .withTimestamp(firstTimestamp)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    expect(person!.last_seen_at!.toMillis()).toBe(baseTime.toMillis())
                })

                // Second event 2 hours later with $update_person_last_seen_at=false should NOT update last_seen_at
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('pageview')
                                .withProperties({ $update_person_last_seen_at: false })
                                .withTimestamp(secondTimestamp)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    // last_seen_at should remain unchanged
                    expect(person!.last_seen_at!.toMillis()).toBe(baseTime.toMillis())
                })
            }
        )

        testWithTeamIngester(
            'should set is_identified to true when merging via $identify with $anon_distinct_id',
            lastSeenAtEnabled,
            async ({ infra, team, kafkaProducer, ingester, token }) => {
                const anonDistinctId = new UUIDT().toString()
                const identifiedDistinctId = new UUIDT().toString()
                const timestamp = DateTime.now().toMillis()

                // First, create an anonymous person
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [new EventBuilder(team, anonDistinctId).withEvent('pageview').withTimestamp(timestamp).build()],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, anonDistinctId)
                    expect(person).toBeDefined()
                    expect(person!.is_identified).toBe(false)
                })

                // Then identify and merge via $anon_distinct_id
                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, identifiedDistinctId)
                                .withEvent('$identify')
                                .withProperties({
                                    $anon_distinct_id: anonDistinctId,
                                    $set: { email: 'user@example.com' },
                                })
                                .withTimestamp(timestamp + 1000)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    // After merge, the person should be identified and accessible via the identified distinct ID
                    const person = await infra.personRepository.fetchPerson(team.id, identifiedDistinctId)
                    expect(person).toBeDefined()
                    expect(person!.is_identified).toBe(true)
                })
            }
        )
    })

    describe(`${configName} - person_last_seen_at_enabled disabled`, () => {
        testWithTeamIngester(
            'should not update last_seen_at when person_last_seen_at_enabled is not set',
            {},
            async ({ infra, team, kafkaProducer, ingester, token }) => {
                const distinctId = new UUIDT().toString()
                const baseTime = DateTime.now().startOf('hour')
                const firstTimestamp = baseTime.toMillis()
                const secondTimestamp = baseTime.plus({ hours: 2 }).toMillis()

                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('$identify')
                                .withProperties({ $set: { initial: true } })
                                .withTimestamp(firstTimestamp)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                let initialLastSeenAt: number | undefined
                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    initialLastSeenAt = person!.last_seen_at?.toMillis()
                })

                await ingester.handleKafkaBatch(
                    createKafkaMessages(
                        [
                            new EventBuilder(team, distinctId)
                                .withEvent('pageview')
                                .withTimestamp(secondTimestamp)
                                .build(),
                        ],
                        token
                    )
                )

                await waitForKafkaMessages(kafkaProducer)

                await waitForExpect(async () => {
                    const person = await infra.personRepository.fetchPerson(team.id, distinctId)
                    expect(person).toBeDefined()
                    expect(person!.last_seen_at?.toMillis()).toBe(initialLastSeenAt)
                })
            }
        )
    })
})
