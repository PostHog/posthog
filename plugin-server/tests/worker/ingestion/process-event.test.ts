import * as IORedis from 'ioredis'
import { DateTime } from 'luxon'

import { Hub, ISOTimestamp, Person, PreIngestionEvent } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { EventsProcessor } from '../../../src/worker/ingestion/process-event'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../../helpers/clickhouse'
import { resetKafka } from '../../helpers/kafka'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')
jest.setTimeout(600000) // 600 sec timeout.

let hub: Hub
let closeHub: () => Promise<void>
let redis: IORedis.Redis
let eventsProcessor: EventsProcessor

beforeAll(async () => {
    await resetKafka()
})

beforeEach(async () => {
    await resetTestDatabase()
    await resetTestDatabaseClickhouse()
    ;[hub, closeHub] = await createHub()
    redis = await hub.redisPool.acquire()
    await redis.flushdb()

    eventsProcessor = new EventsProcessor(hub)
})

afterEach(async () => {
    await hub.redisPool.release(redis)
    await closeHub?.()
})

describe('EventsProcessor#createEvent()', () => {
    let person: Person
    const eventUuid = new UUIDT().toString()
    const personUuid = new UUIDT().toString()
    const timestamp = '2020-02-23T02:15:00.000Z' as ISOTimestamp

    const preIngestionEvent: PreIngestionEvent = {
        eventUuid,
        timestamp,
        distinctId: 'my_id',
        ip: '127.0.0.1',
        teamId: 2,
        event: '$pageview',
        properties: { event: 'property', $set: { foo: 'onEvent' } },
        elementsList: [],
    }

    beforeEach(async () => {
        person = await hub.db.createPerson(
            DateTime.fromISO(timestamp).toUTC(),
            { foo: 'onPerson', pprop: 5 },
            {},
            {},
            2,
            null,
            false,
            personUuid,
            ['my_id']
        )
    })

    it('emits event with person columns, re-using event properties', async () => {
        await eventsProcessor.createEvent(preIngestionEvent, person)

        await eventsProcessor.kafkaProducer.flush()

        const events = await delayUntilEventIngested(() => hub.db.fetchEvents())
        expect(events.length).toEqual(1)
        expect(events[0]).toEqual(
            expect.objectContaining({
                uuid: eventUuid,
                event: '$pageview',
                properties: { event: 'property', $set: { foo: 'onEvent' } },
                timestamp: expect.any(DateTime),
                team_id: 2,
                distinct_id: 'my_id',
                elements_chain: null,
                created_at: expect.any(DateTime),
                person_id: personUuid,
                person_properties: { foo: 'onEvent', pprop: 5 },
                group0_properties: {},
                group1_properties: {},
                group2_properties: {},
                group3_properties: {},
                group4_properties: {},
                $group_0: '',
                $group_1: '',
                $group_2: '',
                $group_3: '',
                $group_4: '',
            })
        )
    })

    it('emits event with group columns', async () => {
        await eventsProcessor.db.insertGroup(
            2,
            0,
            'group_key',
            { group_prop: 'value' },
            DateTime.fromISO(timestamp),
            {},
            {},
            1
        )

        await eventsProcessor.createEvent({ ...preIngestionEvent, properties: { $group_0: 'group_key' } }, person)

        const events = await delayUntilEventIngested(() => hub.db.fetchEvents())
        expect(events.length).toEqual(1)
        expect(events[0]).toEqual(
            expect.objectContaining({
                $group_0: 'group_key',
                $group_1: '',
                $group_2: '',
                $group_3: '',
                $group_4: '',
                group0_properties: {
                    group_prop: 'value',
                },
                group1_properties: {},
                group2_properties: {},
                group3_properties: {},
                group4_properties: {},
            })
        )
    })

    it('handles the person no longer existing', async () => {
        // This person is never in the DB, but createEvent gets a Person object and should use that
        const uuid = new UUIDT().toString()
        const nonExistingPerson: Person = {
            created_at: DateTime.fromISO(timestamp).toUTC(),
            version: 0,
            id: 0,
            team_id: 0,
            properties: { random: 'x' },
            is_user_id: 0,
            is_identified: false,
            uuid: uuid,
            properties_last_updated_at: {},
            properties_last_operation: {},
        }
        await eventsProcessor.createEvent({ ...preIngestionEvent, distinctId: 'no-such-person' }, nonExistingPerson)
        await eventsProcessor.kafkaProducer.flush()

        const events = await delayUntilEventIngested(() => hub.db.fetchEvents())
        expect(events.length).toEqual(1)
        expect(events[0]).toEqual(
            expect.objectContaining({
                uuid: eventUuid,
                distinct_id: 'no-such-person',
                person_id: uuid,
                person_properties: { foo: 'onEvent', random: 'x' },
            })
        )
    })
})
