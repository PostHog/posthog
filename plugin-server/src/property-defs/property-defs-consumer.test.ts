import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { insertHogFunction as _insertHogFunction } from '~/tests/cdp/fixtures'
import { mockProducer } from '~/tests/helpers/mocks/producer.mock'
import { resetTestDatabase } from '~/tests/helpers/sql'

import { ClickHouseEvent, Hub, PropertyType, RawClickHouseEvent, TimestampFormat } from '../types'
import { closeHub, createHub } from '../utils/db/hub'
import { castTimestampOrNow } from '../utils/utils'
import { getPropertyType, PropertyDefsConsumer } from './property-defs-consumer'

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

    beforeEach(async () => {
        fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        offsetIncrementer = 0
        await resetTestDatabase()
        hub = await createHub()

        hub.kafkaProducer = mockProducer
    })

    afterEach(async () => {
        jest.restoreAllMocks()
        if (ingester) {
            await ingester.stop()
        }
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('property types', () => {
        beforeEach(async () => {
            ingester = new PropertyDefsConsumer(hub)
            await ingester.start()
        })

        const testCases: [string, any, PropertyType | null][] = [
            // Special key prefixes
            ['utm_source', 'google', PropertyType.String],
            ['utm_medium', 123, PropertyType.String],
            ['$feature/my_flag', true, PropertyType.String],
            ['$feature_flag_response', false, PropertyType.String],
            ['$survey_response', 'yes', PropertyType.String],
            ['$survey_response_2', 123, PropertyType.String],

            // String values
            ['key', 'hello', PropertyType.String],
            ['key', 'true', PropertyType.Boolean],
            ['key', 'false', PropertyType.Boolean],
            ['key', 'TRUE', PropertyType.Boolean],
            ['key', 'FALSE', PropertyType.Boolean],
            ['key', '2024-01-01T00:00:00Z', PropertyType.DateTime],
            ['key', '2024-01-01T00:00:00+00:00', PropertyType.DateTime],
            ['key', 'invalid-date', PropertyType.String],

            // Number values
            ['key', 123, PropertyType.Numeric],
            ['timestamp', 1234567890, PropertyType.DateTime],
            ['TIME', 1234567890, PropertyType.DateTime],
            ['key', 123.45, PropertyType.Numeric],
            ['key', -123, PropertyType.Numeric],
            ['key', 0, PropertyType.Numeric],
            ['key', NaN, PropertyType.Numeric],
            ['key', Infinity, PropertyType.Numeric],
            ['key', -Infinity, PropertyType.Numeric],

            // Boolean values
            ['key', true, PropertyType.Boolean],
            ['key', false, PropertyType.Boolean],

            // Edge cases
            ['key', null, null],
            ['key', undefined, null],
        ]
        it.each(testCases)('should derive the correct property type for %s: %s', (key, value, expected) => {
            const result = getPropertyType(key, value)

            expect(result).toEqual(expected)
        })
    })

    describe('property updates', () => {
        beforeEach(async () => {
            ingester = new PropertyDefsConsumer(hub)
            await ingester.start()
        })

        it('should write property defs to the DB', async () => {
            const events = await ingester.handleKafkaBatch(createKafkaMessages([createClickHouseEvent({})]))

            // NOTE: Currently we just process without doing anything

            expect(events).toEqual(undefined)
        })
    })
})
