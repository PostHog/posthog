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
import { Message } from 'node-rdkafka'
import { v4 } from 'uuid'

import { waitForExpect } from '~/tests/helpers/expectations'
import { resetKafka } from '~/tests/helpers/kafka'

import { Clickhouse } from '../../tests/helpers/clickhouse'
import { createUserTeamAndOrganization, resetTestDatabase } from '../../tests/helpers/sql'
import { Hub, PersonBatchWritingDbWriteMode, PipelineEvent, ProjectId, Team } from '../types'
import { closeHub, createHub } from '../utils/db/hub'
import { UUIDT } from '../utils/utils'
import { IngestionConsumer } from './ingestion-consumer'

jest.mock('~/utils/token-bucket', () => {
    const mockConsume = jest.fn().mockReturnValue(true)
    return {
        IngestionWarningLimiter: {
            consume: mockConsume,
        },
    }
})

jest.mock('../utils/logger')

const DEFAULT_TEAM: Team = {
    id: 1,
    project_id: 1 as ProjectId,
    uuid: 'team-uuid',
    organization_id: 'org-id',
    name: 'Test Team',
    anonymize_ips: false,
    api_token: 'test-token',
    slack_incoming_webhook: null,
    session_recording_opt_in: false,
    heatmaps_opt_in: null,
    ingested_event: true,
    person_display_name_properties: [],
    person_processing_opt_out: null,
    test_account_filters: [],
    timezone: 'UTC',
    cookieless_server_hash_mode: null,
    available_features: [],
    drop_events_older_than_seconds: null,
}

class EventBuilder {
    private event: Partial<PipelineEvent> = {}

    constructor(team: Team, distinctId: string = new UUIDT().toString()) {
        this.event = {
            event: 'custom event',
            properties: {},
            timestamp: new Date().toISOString(),
            now: new Date().toISOString(),
            ip: null,
            site_url: 'https://example.com',
            uuid: new UUIDT().toString(),
        }
        this.event.distinct_id = distinctId
        this.event.team_id = team.id
        this.event.token = team.api_token
    }

    withEvent(event: string) {
        this.event.event = event
        return this
    }

    withProperties(properties: Record<string, any>) {
        this.event.properties = properties
        return this
    }

    withTimestamp(timestamp: number) {
        const date = DateTime.fromMillis(timestamp)
        this.event.timestamp = date.toString()
        this.event.now = date.toString()
        return this
    }

    build(): PipelineEvent {
        return this.event as PipelineEvent
    }
}

let offsetIncrementer = 0

const createKafkaMessage = (event: PipelineEvent, timestamp: number = Date.now()): Message => {
    // TRICKY: This is the slightly different format that capture sends
    const captureEvent = {
        uuid: event.uuid,
        distinct_id: event.distinct_id,
        ip: event.ip,
        now: event.now,
        token: event.token,
        data: JSON.stringify(event),
    }
    return {
        key: `${event.token}:${event.distinct_id}`,
        value: Buffer.from(JSON.stringify(captureEvent)),
        size: 1,
        topic: 'test',
        offset: offsetIncrementer++,
        timestamp: timestamp + offsetIncrementer,
        partition: 1,
    }
}

const createKafkaMessages = (events: PipelineEvent[]): Message[] => {
    return events.map((event) => createKafkaMessage(event))
}

const waitForKafkaMessages = async (hub: Hub) => {
    await hub.kafkaProducer.flush()
}

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
    let clickhouse: Clickhouse
    let hub: Hub
    let ingester: IngestionConsumer
    let team: Team

    beforeAll(async () => {
        clickhouse = Clickhouse.create()
        await resetKafka()
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
    })

    afterAll(async () => {
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        clickhouse.close()
    })

    beforeEach(async () => {
        hub = await createHub({
            ...config,
        })

        const teamId = Math.floor((Date.now() % 1000000000) + Math.random() * 1000000)
        const userId = teamId
        const organizationId = new UUIDT().toString()
        const userUuid = new UUIDT().toString()
        const organizationMembershipId = new UUIDT().toString()

        team = {
            ...DEFAULT_TEAM,
            id: teamId,
            project_id: teamId as ProjectId,
            organization_id: organizationId,
            uuid: v4(),
            name: teamId.toString(),
        }

        await createUserTeamAndOrganization(
            hub.postgres,
            team.id,
            userId,
            userUuid,
            team.organization_id,
            organizationMembershipId
        )

        const fetchedTeam = await hub.teamManager.getTeam(team.id)
        if (!fetchedTeam) {
            throw new Error(`Failed to fetch team ${team.id} from database`)
        }
        team = fetchedTeam

        ingester = new IngestionConsumer(hub)
        ingester['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn(),
        } as any

        await ingester.start()
    })

    afterEach(async () => {
        await ingester.stop()
        await closeHub(hub)
    })

    describe(configName, () => {
        it('should create a new person on first event', async () => {
            const distinctId = new UUIDT().toString()

            await ingester.handleKafkaBatch(
                createKafkaMessages([new EventBuilder(team, distinctId).withEvent('test_event').build()])
            )

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const person = await hub.personRepository.fetchPerson(team.id, distinctId)
                expect(person).toBeDefined()
                expect(person!.team_id).toBe(team.id)
            })
        })

        it('should set person properties with $identify and $set', async () => {
            const distinctId = new UUIDT().toString()
            const timestamp = DateTime.now().toMillis()

            // Create person with initial properties
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, distinctId)
                        .withEvent('$identify')
                        .withProperties({
                            $set: { name: 'Initial Name', email: 'test@example.com' },
                        })
                        .withTimestamp(timestamp)
                        .build(),
                ])
            )

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const person = await hub.personRepository.fetchPerson(team.id, distinctId)
                expect(person).toBeDefined()
                expect(person!.properties).toEqual(
                    expect.objectContaining({
                        name: 'Initial Name',
                        email: 'test@example.com',
                    })
                )
            })
        })

        it('should update person properties across multiple events in same batch', async () => {
            const distinctId = new UUIDT().toString()
            const timestamp = DateTime.now().toMillis()

            // Send multiple events in a single batch
            await ingester.handleKafkaBatch(
                createKafkaMessages([
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
                ])
            )

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const person = await hub.personRepository.fetchPerson(team.id, distinctId)
                expect(person).toBeDefined()
                expect(person!.properties).toEqual(
                    expect.objectContaining({
                        prop1: 'value1',
                        prop2: 'value2',
                    })
                )
            })
        })

        it('should update person properties across multiple batches', async () => {
            const distinctId = new UUIDT().toString()
            const timestamp = DateTime.now().toMillis()

            // First batch: create person
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, distinctId)
                        .withEvent('$identify')
                        .withProperties({
                            $set: { initial_prop: 'initial_value' },
                        })
                        .withTimestamp(timestamp)
                        .build(),
                ])
            )

            await waitForKafkaMessages(hub)

            // Wait for person to be created
            await waitForExpect(async () => {
                const person = await hub.personRepository.fetchPerson(team.id, distinctId)
                expect(person).toBeDefined()
                expect(person!.properties).toEqual(
                    expect.objectContaining({
                        initial_prop: 'initial_value',
                    })
                )
            })

            // Second batch: update person
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, distinctId)
                        .withEvent('$identify')
                        .withProperties({
                            $set: { new_prop: 'new_value', updated_prop: 'updated' },
                        })
                        .withTimestamp(timestamp + 1000)
                        .build(),
                ])
            )

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const person = await hub.personRepository.fetchPerson(team.id, distinctId)
                expect(person).toBeDefined()
                expect(person!.properties).toEqual(
                    expect.objectContaining({
                        initial_prop: 'initial_value',
                        new_prop: 'new_value',
                        updated_prop: 'updated',
                    })
                )
            })
        })

        it('should handle $set_once correctly', async () => {
            const distinctId = new UUIDT().toString()
            const timestamp = DateTime.now().toMillis()

            // First event sets initial value
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, distinctId)
                        .withEvent('$identify')
                        .withProperties({
                            $set_once: { first_seen: 'original_value' },
                        })
                        .withTimestamp(timestamp)
                        .build(),
                ])
            )

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const person = await hub.personRepository.fetchPerson(team.id, distinctId)
                expect(person).toBeDefined()
                expect(person!.properties).toEqual(
                    expect.objectContaining({
                        first_seen: 'original_value',
                    })
                )
            })

            // Second event tries to overwrite with $set_once - should be ignored
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, distinctId)
                        .withEvent('$identify')
                        .withProperties({
                            $set_once: { first_seen: 'should_be_ignored' },
                        })
                        .withTimestamp(timestamp + 1000)
                        .build(),
                ])
            )

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const person = await hub.personRepository.fetchPerson(team.id, distinctId)
                expect(person).toBeDefined()
                // Value should remain unchanged
                expect(person!.properties.first_seen).toBe('original_value')
            })
        })

        it('should handle $unset correctly', async () => {
            const distinctId = new UUIDT().toString()
            const timestamp = DateTime.now().toMillis()

            // Create person with properties
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, distinctId)
                        .withEvent('$identify')
                        .withProperties({
                            $set: { keep_prop: 'keep', remove_prop: 'remove' },
                        })
                        .withTimestamp(timestamp)
                        .build(),
                ])
            )

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const person = await hub.personRepository.fetchPerson(team.id, distinctId)
                expect(person).toBeDefined()
                expect(person!.properties).toHaveProperty('remove_prop')
            })

            // Unset a property
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, distinctId)
                        .withEvent('$identify')
                        .withProperties({
                            $unset: ['remove_prop'],
                        })
                        .withTimestamp(timestamp + 1000)
                        .build(),
                ])
            )

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const person = await hub.personRepository.fetchPerson(team.id, distinctId)
                expect(person).toBeDefined()
                expect(person!.properties).toEqual(
                    expect.objectContaining({
                        keep_prop: 'keep',
                    })
                )
                expect(person!.properties).not.toHaveProperty('remove_prop')
            })
        })

        it('should handle combined $set and $unset in same event', async () => {
            const distinctId = new UUIDT().toString()
            const timestamp = DateTime.now().toMillis()

            // Create person with initial properties
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, distinctId)
                        .withEvent('$identify')
                        .withProperties({
                            $set: { prop1: 'value1', prop2: 'value2', prop3: 'value3' },
                        })
                        .withTimestamp(timestamp)
                        .build(),
                ])
            )

            await waitForKafkaMessages(hub)

            // Update with combined $set and $unset
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, distinctId)
                        .withEvent('$identify')
                        .withProperties({
                            $set: { prop1: 'updated_value1', prop4: 'value4' },
                            $unset: ['prop2'],
                        })
                        .withTimestamp(timestamp + 1000)
                        .build(),
                ])
            )

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const person = await hub.personRepository.fetchPerson(team.id, distinctId)
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
        })

        it('should set is_identified to true when merging via $identify with $anon_distinct_id', async () => {
            const anonDistinctId = new UUIDT().toString()
            const identifiedDistinctId = new UUIDT().toString()
            const timestamp = DateTime.now().toMillis()

            // First, create an anonymous person
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, anonDistinctId).withEvent('pageview').withTimestamp(timestamp).build(),
                ])
            )

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const person = await hub.personRepository.fetchPerson(team.id, anonDistinctId)
                expect(person).toBeDefined()
                expect(person!.is_identified).toBe(false)
            })

            // Then identify and merge via $anon_distinct_id
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, identifiedDistinctId)
                        .withEvent('$identify')
                        .withProperties({
                            $anon_distinct_id: anonDistinctId,
                            $set: { email: 'user@example.com' },
                        })
                        .withTimestamp(timestamp + 1000)
                        .build(),
                ])
            )

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                // After merge, the person should be identified and accessible via the identified distinct ID
                const person = await hub.personRepository.fetchPerson(team.id, identifiedDistinctId)
                expect(person).toBeDefined()
                expect(person!.is_identified).toBe(true)
            })
        })
    })
})
