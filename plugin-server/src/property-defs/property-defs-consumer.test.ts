import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { mockProducer } from '~/tests/helpers/mocks/producer.mock'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { insertHogFunction as _insertHogFunction } from '../cdp/_tests/fixtures'
import { ClickHouseEvent, Hub, RawClickHouseEvent, Team, TimestampFormat } from '../types'
import { closeHub, createHub } from '../utils/db/hub'
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

describe('PropertyDefsConsumer', () => {
    let ingester: PropertyDefsConsumer
    let hub: Hub
    let fixedTime: DateTime
    let team: Team
    let propertyDefsDB: PropertyDefsDB

    beforeEach(async () => {
        fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        offsetIncrementer = 0
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        ingester = new PropertyDefsConsumer(hub)

        hub.kafkaProducer = mockProducer
        propertyDefsDB = ingester['propertyDefsDB']

        jest.spyOn(propertyDefsDB, 'writeEventDefinition')
        jest.spyOn(propertyDefsDB, 'writePropertyDefinition')
        jest.spyOn(propertyDefsDB, 'writeEventProperty')
    })

    afterEach(async () => {
        jest.restoreAllMocks()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('property updates', () => {
        it('should write property defs to the DB', async () => {
            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    createClickHouseEvent({
                        team_id: team.id,
                        properties: {
                            url: 'http://example.com',
                        },
                    }),
                ])
            )

            expect(propertyDefsDB.writeEventDefinition).toHaveBeenCalledTimes(1)
            expect(propertyDefsDB.writePropertyDefinition).toHaveBeenCalledTimes(1)
            expect(propertyDefsDB.writeEventProperty).toHaveBeenCalledTimes(1)

            expect(forSnapshot(await propertyDefsDB.listEventDefinitions(team.id))).toMatchInlineSnapshot(`
                [
                  {
                    "created_at": "2025-01-01T00:00:00.000Z",
                    "id": "<REPLACED-UUID-0>",
                    "last_seen_at": "2025-01-01T00:00:00.000Z",
                    "name": "$pageview",
                    "project_id": "2",
                    "query_usage_30_day": null,
                    "team_id": 2,
                    "volume_30_day": null,
                  },
                ]
            `)

            expect(
                forSnapshot(await propertyDefsDB.listEventProperties(team.id), {
                    overrides: { id: '<REPLACED_NUMBER>' },
                })
            ).toMatchInlineSnapshot(`
                [
                  {
                    "event": "$pageview",
                    "id": "<REPLACED_NUMBER>",
                    "project_id": "2",
                    "property": "url",
                    "team_id": 2,
                  },
                ]
            `)

            expect(forSnapshot(await propertyDefsDB.listPropertyDefinitions(team.id))).toMatchInlineSnapshot(`
                [
                  {
                    "group_type_index": null,
                    "id": "<REPLACED-UUID-0>",
                    "is_numerical": false,
                    "name": "url",
                    "project_id": "2",
                    "property_type": "String",
                    "property_type_format": null,
                    "query_usage_30_day": null,
                    "team_id": 2,
                    "type": 1,
                    "volume_30_day": null,
                  },
                ]
            `)
        })
    })
})
