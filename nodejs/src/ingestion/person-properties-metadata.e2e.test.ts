/**
 * Integration tests verifying that properties_last_updated_at and properties_last_operation
 * fields are only set at person creation time, NOT when properties are updated afterwards.
 *
 * This documents the current behavior which causes issues for the person property
 * reconciliation script - it cannot reliably determine which property value is newer
 * because these metadata fields are not maintained on updates.
 */
import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { v4 } from 'uuid'

import { waitForExpect } from '~/tests/helpers/expectations'
import { resetKafka } from '~/tests/helpers/kafka'

import { createUserTeamAndOrganization, fetchPostgresPersons, resetTestDatabase } from '../../tests/helpers/sql'
import { Hub, PipelineEvent, PluginsServerConfig, ProjectId, Team } from '../types'
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

const waitForKafkaMessages = async (hub: Hub) => {
    await hub.kafkaProducer.flush()
}

const DEFAULT_TEAM: Team = {
    id: 2,
    project_id: 2 as ProjectId,
    organization_id: '2',
    uuid: v4(),
    name: '2',
    anonymize_ips: true,
    api_token: 'api_token',
    slack_incoming_webhook: 'slack_incoming_webhook',
    session_recording_opt_in: true,
    person_processing_opt_out: null,
    heatmaps_opt_in: null,
    ingested_event: true,
    person_display_name_properties: null,
    test_account_filters: null,
    cookieless_server_hash_mode: null,
    timezone: 'UTC',
    available_features: [],
    drop_events_older_than_seconds: null,
}

let offsetIncrementer = 0

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

const createKafkaMessage = (event: PipelineEvent, timestamp: number = DateTime.now().toMillis()): Message => {
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
    return events.map(createKafkaMessage)
}

const createTestWithTeamIngester = (baseConfig: Partial<PluginsServerConfig> = {}) => {
    return (
        name: string,
        config: { teamOverrides?: Partial<Team>; pluginServerConfig?: Partial<PluginsServerConfig> } = {},
        testFn: (ingester: IngestionConsumer, hub: Hub, team: Team) => Promise<void>
    ) => {
        test(name, async () => {
            const hub = await createHub({
                APP_METRICS_FLUSH_FREQUENCY_MS: 0,
                ...baseConfig,
                ...config.pluginServerConfig,
            })

            const teamId = Math.floor((Date.now() % 1000000000) + Math.random() * 1000000)
            const userId = teamId
            const organizationId = new UUIDT().toString()

            const newTeam: Team = {
                ...DEFAULT_TEAM,
                id: teamId,
                project_id: teamId as ProjectId,
                organization_id: organizationId,
                uuid: v4(),
                name: teamId.toString(),
                ...config.teamOverrides,
            }
            const userUuid = new UUIDT().toString()
            const organizationMembershipId = new UUIDT().toString()

            await createUserTeamAndOrganization(
                hub.postgres,
                newTeam.id,
                userId,
                userUuid,
                newTeam.organization_id,
                organizationMembershipId,
                config.teamOverrides
            )

            const fetchedTeam = await hub.teamManager.getTeam(newTeam.id)
            if (!fetchedTeam) {
                throw new Error(`Failed to fetch team ${newTeam.id} from database`)
            }

            const ingester = new IngestionConsumer(hub)
            ingester['kafkaConsumer'] = {
                connect: jest.fn(),
                disconnect: jest.fn(),
                isHealthy: jest.fn(),
            } as any

            await ingester.start()
            await testFn(ingester, hub, fetchedTeam)
            await ingester.stop()
            await closeHub(hub)
        })
    }
}

describe('Person properties_last_updated_at and properties_last_operation behavior', () => {
    const testWithTeamIngester = createTestWithTeamIngester()

    beforeAll(async () => {
        await resetKafka()
        await resetTestDatabase()
        process.env.SITE_URL = 'https://example.com'
    })

    afterAll(async () => {
        await resetTestDatabase()
    })

    testWithTeamIngester(
        'does set properties_last_updated_at and properties_last_operation when creating person via $set',
        {},
        async (ingester, hub, team) => {
            const distinctId = new UUIDT().toString()
            const timestamp = DateTime.now().toMillis()

            // Send an event with $set that will create a new person
            const events = [
                new EventBuilder(team, distinctId)
                    .withEvent('test_event')
                    .withProperties({
                        $set: { email: 'test@example.com', name: 'Test User' },
                    })
                    .withTimestamp(timestamp)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.postgres, team.id)
                expect(persons.length).toBe(1)

                const person = persons[0]

                // Verify properties were set
                expect(person.properties).toMatchObject({
                    email: 'test@example.com',
                    name: 'Test User',
                })

                // Verify properties_last_updated_at has entries for both properties
                expect(person.properties_last_updated_at).toBeDefined()
                expect(person.properties_last_updated_at.email).toBeDefined()
                expect(person.properties_last_updated_at.name).toBeDefined()

                // Verify properties_last_operation has entries for both properties
                expect(person.properties_last_operation).toBeDefined()
                expect(person.properties_last_operation?.email).toBe('set')
                expect(person.properties_last_operation?.name).toBe('set')
            })
        }
    )

    testWithTeamIngester(
        'does set properties_last_updated_at and properties_last_operation when creating person via $identify',
        {},
        async (ingester, hub, team) => {
            const distinctId = new UUIDT().toString()
            const timestamp = DateTime.now().toMillis()

            // Send $identify event that will create a new person with properties
            const events = [
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({
                        $set: { email: 'identify@example.com' },
                        $set_once: { initial_source: 'organic' },
                    })
                    .withTimestamp(timestamp)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.postgres, team.id)
                expect(persons.length).toBe(1)

                const person = persons[0]

                // Verify properties were set
                expect(person.properties).toMatchObject({
                    email: 'identify@example.com',
                    initial_source: 'organic',
                })

                // Verify properties_last_updated_at has entries
                expect(person.properties_last_updated_at).toBeDefined()
                expect(person.properties_last_updated_at.email).toBeDefined()
                expect(person.properties_last_updated_at.initial_source).toBeDefined()

                // Verify properties_last_operation has correct operation types
                expect(person.properties_last_operation).toBeDefined()
                expect(person.properties_last_operation?.email).toBe('set')
                expect(person.properties_last_operation?.initial_source).toBe('set_once')
            })
        }
    )

    testWithTeamIngester(
        'DOES NOT update properties_last_updated_at when updating existing property after person creation',
        {},
        async (ingester, hub, team) => {
            const distinctId = new UUIDT().toString()
            const t1 = DateTime.now().toMillis()
            const t2 = t1 + 60000 // 1 minute later

            // First event: Create person with initial property
            const createEvents = [
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({
                        $set: { email: 'original@example.com' },
                    })
                    .withTimestamp(t1)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(createEvents))
            await waitForKafkaMessages(hub)

            // Wait for person to be created and capture the initial timestamp
            let initialTimestamp: string | undefined
            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.postgres, team.id)
                expect(persons.length).toBe(1)
                expect(persons[0].properties.email).toBe('original@example.com')
                initialTimestamp = persons[0].properties_last_updated_at?.email
                expect(initialTimestamp).toBeDefined()
            })

            // Second event: Update the same property
            const updateEvents = [
                new EventBuilder(team, distinctId)
                    .withEvent('$set')
                    .withProperties({
                        $set: { email: 'updated@example.com' },
                    })
                    .withTimestamp(t2)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(updateEvents))
            await waitForKafkaMessages(hub)

            // Verify property was updated but timestamp was NOT
            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.postgres, team.id)
                expect(persons.length).toBe(1)

                const person = persons[0]

                // Property value should be updated
                expect(person.properties.email).toBe('updated@example.com')

                // THIS IS THE KEY ASSERTION:
                // properties_last_updated_at should still have the ORIGINAL timestamp from creation
                // It should NOT be updated to t2
                expect(person.properties_last_updated_at?.email).toBe(initialTimestamp)
            })
        }
    )

    testWithTeamIngester(
        'DOES NOT add properties_last_updated_at entry when adding NEW property after person creation',
        {},
        async (ingester, hub, team) => {
            const distinctId = new UUIDT().toString()
            const t1 = DateTime.now().toMillis()
            const t2 = t1 + 60000 // 1 minute later

            // First event: Create person with initial property
            const createEvents = [
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({
                        $set: { email: 'test@example.com' },
                    })
                    .withTimestamp(t1)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(createEvents))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.postgres, team.id)
                expect(persons.length).toBe(1)
                expect(persons[0].properties_last_updated_at?.email).toBeDefined()
            })

            // Second event: Add a NEW property (not updating existing one)
            const addPropertyEvents = [
                new EventBuilder(team, distinctId)
                    .withEvent('$set')
                    .withProperties({
                        $set: { name: 'New Name' },
                    })
                    .withTimestamp(t2)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(addPropertyEvents))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.postgres, team.id)
                expect(persons.length).toBe(1)

                const person = persons[0]

                // New property should exist
                expect(person.properties.name).toBe('New Name')

                // THIS IS THE KEY ASSERTION:
                // properties_last_updated_at should NOT have an entry for the new property
                // because it was added after person creation
                expect(person.properties_last_updated_at?.name).toBeUndefined()

                // Original property's timestamp should still exist
                expect(person.properties_last_updated_at?.email).toBeDefined()
            })
        }
    )

    testWithTeamIngester(
        'DOES NOT update properties_last_operation when updating existing property after person creation',
        {},
        async (ingester, hub, team) => {
            const distinctId = new UUIDT().toString()
            const t1 = DateTime.now().toMillis()
            const t2 = t1 + 60000 // 1 minute later

            // First event: Create person with $set_once property
            const createEvents = [
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({
                        $set_once: { initial_value: 'first' },
                    })
                    .withTimestamp(t1)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(createEvents))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.postgres, team.id)
                expect(persons.length).toBe(1)
                expect(persons[0].properties.initial_value).toBe('first')
                expect(persons[0].properties_last_operation?.initial_value).toBe('set_once')
            })

            // Second event: Try to update the same property with $set (different operation)
            // Note: $set_once won't overwrite, but if we use $set on a different property
            // that was originally set with $set_once, the operation type should theoretically change
            // but it won't because properties_last_operation is not maintained
            const updateEvents = [
                new EventBuilder(team, distinctId)
                    .withEvent('$set')
                    .withProperties({
                        // Use $set to update email which will be new
                        $set: { email: 'test@example.com' },
                    })
                    .withTimestamp(t2)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(updateEvents))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.postgres, team.id)
                expect(persons.length).toBe(1)

                const person = persons[0]

                // New property should exist
                expect(person.properties.email).toBe('test@example.com')

                // THIS IS THE KEY ASSERTION:
                // properties_last_operation should NOT have an entry for the new property
                // because it was added after person creation
                expect(person.properties_last_operation?.email).toBeUndefined()

                // Original property's operation should still be set_once
                expect(person.properties_last_operation?.initial_value).toBe('set_once')
            })
        }
    )

    testWithTeamIngester(
        'DOES NOT add properties_last_operation entry when adding NEW property after person creation',
        {},
        async (ingester, hub, team) => {
            const distinctId = new UUIDT().toString()
            const t1 = DateTime.now().toMillis()
            const t2 = t1 + 60000 // 1 minute later

            // First event: Create person with initial property via $set
            const createEvents = [
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({
                        $set: { email: 'test@example.com' },
                    })
                    .withTimestamp(t1)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(createEvents))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.postgres, team.id)
                expect(persons.length).toBe(1)
                expect(persons[0].properties_last_operation?.email).toBe('set')
            })

            // Second event: Add a NEW property via $set_once
            const addPropertyEvents = [
                new EventBuilder(team, distinctId)
                    .withEvent('$set')
                    .withProperties({
                        $set_once: { initial_source: 'organic' },
                    })
                    .withTimestamp(t2)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(addPropertyEvents))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.postgres, team.id)
                expect(persons.length).toBe(1)

                const person = persons[0]

                // New property should exist
                expect(person.properties.initial_source).toBe('organic')

                // THIS IS THE KEY ASSERTION:
                // properties_last_operation should NOT have an entry for the new property
                // because it was added after person creation
                expect(person.properties_last_operation?.initial_source).toBeUndefined()

                // Original property's operation should still exist
                expect(person.properties_last_operation?.email).toBe('set')
            })
        }
    )
})
