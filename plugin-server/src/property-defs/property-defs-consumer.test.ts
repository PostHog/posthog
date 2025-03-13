import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { mockProducer } from '~/tests/helpers/mocks/producer.mock'
import { forSnapshot as _forSnapshot } from '~/tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { insertHogFunction as _insertHogFunction } from '../cdp/_tests/fixtures'
import { ClickHouseEvent, Hub, ProjectId, RawClickHouseEvent, Team, TimestampFormat } from '../types'
import { closeHub, createHub } from '../utils/db/hub'
import { PostgresUse } from '../utils/db/postgres'
import { castTimestampOrNow } from '../utils/utils'
import { PropertyDefsConsumer } from './property-defs-consumer'
import { PropertyDefsDB } from './services/property-defs-db'

const DEFAULT_TEST_TIMEOUT = 5000
jest.setTimeout(DEFAULT_TEST_TIMEOUT)

const mockConsumer = {
    on: jest.fn(),
    commitSync: jest.fn(),
    commit: jest.fn(),
    queryWatermarkOffsets: jest.fn(),
    committed: jest.fn(),
    assignments: jest.fn(),
    isConnected: jest.fn(() => true),
    getMetadata: jest.fn(),
}

jest.mock('../../src/kafka/batch-consumer', () => {
    return {
        startBatchConsumer: jest.fn(() =>
            Promise.resolve({
                join: () => ({
                    finally: jest.fn(),
                }),
                stop: jest.fn(),
                consumer: mockConsumer,
            })
        ),
    }
})

let offsetIncrementer = 0

const createRawClickHouseEvent = (event: ClickHouseEvent): RawClickHouseEvent => {
    // Inverts the parsing for simpler tests
    return {
        ...event,
        properties: JSON.stringify(event.properties),
        timestamp: castTimestampOrNow(event.timestamp ?? null, TimestampFormat.ClickHouse),
        created_at: castTimestampOrNow(event.created_at ?? null, TimestampFormat.ClickHouse),
        elements_chain: JSON.stringify(event.elements_chain),
        person_created_at: castTimestampOrNow(event.person_created_at ?? null, TimestampFormat.ClickHouse),
        person_properties: JSON.stringify(event.person_properties),
        group0_created_at: castTimestampOrNow(event.group0_created_at ?? null, TimestampFormat.ClickHouse),
        group0_properties: event.group0_properties ? JSON.stringify(event.group0_properties) : undefined,
        group1_created_at: castTimestampOrNow(event.group1_created_at ?? null, TimestampFormat.ClickHouse),
        group1_properties: event.group1_properties ? JSON.stringify(event.group1_properties) : undefined,
        group2_created_at: castTimestampOrNow(event.group2_created_at ?? null, TimestampFormat.ClickHouse),
        group2_properties: event.group2_properties ? JSON.stringify(event.group2_properties) : undefined,
        group3_created_at: castTimestampOrNow(event.group3_created_at ?? null, TimestampFormat.ClickHouse),
        group3_properties: event.group3_properties ? JSON.stringify(event.group3_properties) : undefined,
        group4_created_at: castTimestampOrNow(event.group4_created_at ?? null, TimestampFormat.ClickHouse),
        group4_properties: event.group4_properties ? JSON.stringify(event.group4_properties) : undefined,
    }
}

const createClickHouseEvent = (event: Partial<ClickHouseEvent> = {}): ClickHouseEvent => {
    return {
        uuid: event.uuid ?? '123',
        event: event.event ?? '$pageview',
        team_id: event.team_id ?? 1,
        project_id: event.project_id ?? (1 as ProjectId),
        distinct_id: event.distinct_id ?? 'distinct_id_1',
        /** Person UUID. */
        person_id: event.person_id ?? undefined,

        timestamp: DateTime.now(),
        created_at: DateTime.now(),
        properties: event.properties ?? {},
        elements_chain: event.elements_chain ?? null,
        person_created_at: event.person_created_at ?? null,
        person_properties: event.person_properties ?? {},
        group0_properties: event.group0_properties ?? {},
        group1_properties: event.group1_properties ?? {},
        group2_properties: event.group2_properties ?? {},
        group3_properties: event.group3_properties ?? {},
        group4_properties: event.group4_properties ?? {},
        group0_created_at: event.group0_created_at ?? null,
        group1_created_at: event.group1_created_at ?? null,
        group2_created_at: event.group2_created_at ?? null,
        group3_created_at: event.group3_created_at ?? null,
        group4_created_at: event.group4_created_at ?? null,
        person_mode: event.person_mode ?? 'full',
    }
}

const createKafkaMessages: (events: ClickHouseEvent[]) => Message[] = (events) => {
    return events.map((event) => {
        // TRICKY: This is the slightly different format that capture sends
        return {
            value: Buffer.from(JSON.stringify(createRawClickHouseEvent(event))),
            size: 1,
            topic: 'test',
            offset: offsetIncrementer++,
            timestamp: DateTime.now().toMillis(),
            partition: 1,
        }
    })
}

/**
 * TEST CASES TO COVER:
 * - $groupidentify
 *   - Should create group properties from the $group_set property
 *   - Should create property properties from its own event properties
 *   - Should limit to the max number of groups using the group types
 * - batching
 *   - Should only write once per unique constraint (team_id, event, property etc)
 */

describe('PropertyDefsConsumer', () => {
    let ingester: PropertyDefsConsumer
    let hub: Hub
    let fixedTime: DateTime
    let team: Team
    let propertyDefsDB: PropertyDefsDB

    const advanceTime = (amount: number) => {
        fixedTime = fixedTime.plus({ seconds: amount })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
    }

    beforeEach(async () => {
        fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        offsetIncrementer = 0
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)

        // Create some default group type mappings
        const groupTypeMappings = [
            { group_type: 'group-a', group_type_index: 0 },
            { group_type: 'group-b', group_type_index: 1 },
        ]
        for (const mapping of groupTypeMappings) {
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_grouptypemapping (team_id, project_id, group_type, group_type_index) VALUES ($1, $2, $3, $4)`,
                [team.id, team.project_id, mapping.group_type, mapping.group_type_index],
                'createGroupTypeMappings'
            )
        }

        hub.PROPERTY_DEFS_CONSUMER_ENABLED_TEAMS = '*'
        ingester = new PropertyDefsConsumer(hub)

        hub.kafkaProducer = mockProducer
        propertyDefsDB = ingester['propertyDefsDB']

        jest.spyOn(propertyDefsDB, 'writeEventDefinitions')
        jest.spyOn(propertyDefsDB, 'writePropertyDefinitions')
        jest.spyOn(propertyDefsDB, 'writeEventProperties')
    })

    afterEach(async () => {
        jest.restoreAllMocks()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    const forSnapshot = <T>(value: T, overrides: Record<string, string> = {}): T => {
        return _forSnapshot(value, {
            overrides: {
                // Dates are tricky as it comes from the DB so is timezone dependent
                created_at: '<REPLACED_DATE>',
                last_seen_at: '<REPLACED_DATE>',
                ...overrides,
            },
        })
    }

    describe('property updates', () => {
        it('should write simple property defs to the DB', async () => {
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    createClickHouseEvent({
                        team_id: team.id,
                        project_id: team.project_id,
                        properties: {
                            url: 'http://example.com',
                        },
                    }),
                ])
            )

            expect(propertyDefsDB.writeEventDefinitions).toHaveBeenCalledTimes(1)
            expect(propertyDefsDB.writePropertyDefinitions).toHaveBeenCalledTimes(1)
            expect(propertyDefsDB.writeEventProperties).toHaveBeenCalledTimes(1)

            expect(forSnapshot(await propertyDefsDB.listEventDefinitions(team.id))).toMatchSnapshot()

            expect(
                forSnapshot(await propertyDefsDB.listEventProperties(team.id), {
                    // NOTE: The event properties are not sorted by the DB so we need to sort them to be deterministic
                    id: '<REPLACED_NUMBER>',
                })
            ).toMatchSnapshot()

            expect(forSnapshot(await propertyDefsDB.listPropertyDefinitions(team.id))).toMatchSnapshot()
        })

        it('should only write the first seen property defs to the DB', async () => {
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    createClickHouseEvent({
                        team_id: team.id,
                        project_id: team.project_id,
                        properties: {
                            url: 'http://example.com',
                        },
                    }),
                    createClickHouseEvent({
                        team_id: team.id,
                        project_id: team.project_id,
                        properties: {
                            url: 2,
                        },
                    }),
                    createClickHouseEvent({
                        team_id: team.id,
                        project_id: team.project_id,
                        properties: {
                            url: 5,
                        },
                    }),
                ])
            )

            expect(propertyDefsDB.writeEventDefinitions).toHaveBeenCalledTimes(1)
            expect(propertyDefsDB.writePropertyDefinitions).toHaveBeenCalledTimes(1)
            expect(propertyDefsDB.writeEventProperties).toHaveBeenCalledTimes(1)

            // Snapshot shows a String type as it was the first seen value
            expect(forSnapshot(await propertyDefsDB.listPropertyDefinitions(team.id))).toMatchSnapshot()
        })

        it('should batch multiple writes', async () => {
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    createClickHouseEvent({
                        team_id: team.id,
                        project_id: team.project_id,
                        event: 'event1',
                        properties: {
                            url: 'http://example.com',
                        },
                    }),
                    createClickHouseEvent({
                        team_id: team.id,
                        project_id: team.project_id,
                        event: 'event2',
                        properties: {
                            foo: 'bar',
                            test: 4,
                        },
                    }),
                ])
            )

            expect(propertyDefsDB.writeEventDefinitions).toHaveBeenCalledTimes(1)
            expect(propertyDefsDB.writePropertyDefinitions).toHaveBeenCalledTimes(1)
            expect(propertyDefsDB.writeEventProperties).toHaveBeenCalledTimes(1)

            // Snapshot shows a String type as it was the first seen value
            expect(forSnapshot(await propertyDefsDB.listPropertyDefinitions(team.id))).toMatchSnapshot()
        })

        it('should handle existing property defs', async () => {
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    createClickHouseEvent({
                        team_id: team.id,
                        project_id: team.project_id,
                        event: 'event1',
                        properties: {
                            foo: 1,
                        },
                    }),
                ])
            )
            expect(forSnapshot(await propertyDefsDB.listPropertyDefinitions(team.id))).toMatchSnapshot()

            advanceTime(1000)

            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    createClickHouseEvent({
                        team_id: team.id,
                        project_id: team.project_id,
                        event: 'event1',
                        properties: {
                            other: 'property',
                        },
                    }),
                    createClickHouseEvent({
                        team_id: team.id,
                        project_id: team.project_id,
                        event: 'event1',
                        properties: {
                            foo: 'changed!!',
                        },
                    }),
                ])
            )

            // Contains both properties but only one updated
            expect(forSnapshot(await propertyDefsDB.listPropertyDefinitions(team.id))).toMatchSnapshot()
        })
    })

    describe('group updates', () => {
        it('should create group properties from the $group_set property', async () => {
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    createClickHouseEvent({
                        team_id: team.id,
                        project_id: team.project_id,
                        event: '$groupidentify',
                        properties: {
                            $group_type: 'group-a',
                            $group_key: 'key-1',
                            $group_set: {
                                prop1: 'foo',
                                prop2: 2,
                            },
                        },
                    }),
                ])
            )

            expect(propertyDefsDB.writeEventDefinitions).toHaveBeenCalledTimes(1)
            expect(propertyDefsDB.writePropertyDefinitions).toHaveBeenCalledTimes(1)
            expect(propertyDefsDB.writeEventProperties).toHaveBeenCalledTimes(1)

            expect(forSnapshot(await propertyDefsDB.listEventDefinitions(team.id))).toMatchSnapshot()
            expect(forSnapshot(await propertyDefsDB.listPropertyDefinitions(team.id))).toMatchSnapshot()
        })
    })
})
