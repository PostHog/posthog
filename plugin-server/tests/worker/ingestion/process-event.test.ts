import * as IORedis from 'ioredis'
import { Consumer, Kafka, KafkaMessage } from 'kafkajs'
import { DateTime } from 'luxon'

import { KAFKA_EVENTS_JSON } from '../../../src/config/kafka-topics'
import { Hub, ISOTimestamp, Person, PreIngestionEvent } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { EventsProcessor } from '../../../src/worker/ingestion/process-event'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../../helpers/clickhouse'
import { resetKafka } from '../../helpers/kafka'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')
jest.setTimeout(600000) // 600 sec timeout.

let hub: Hub
let kafka: Kafka
let redis: IORedis.Redis
let eventsProcessor: EventsProcessor

beforeAll(async () => {
    kafka = await resetKafka()
})

beforeEach(async () => {
    await resetTestDatabase()
    await resetTestDatabaseClickhouse()
    hub = await createHub()
    redis = await hub.redisPool.acquire()
    await redis.flushdb()

    eventsProcessor = new EventsProcessor(hub)
})

afterEach(async () => {
    await hub.redisPool.release(redis)
    await closeHub(hub)
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
        teamId: 2,
        projectId: 1,
        event: '$pageview',
        properties: { event: 'property', $set: { foo: 'onEvent' } },
    }

    let kafkaEvents: KafkaMessage[]
    let kafkaEventsConsumer: Consumer

    beforeAll(async () => {
        kafkaEventsConsumer = kafka.consumer({ groupId: 'process-event-test' })
        await kafkaEventsConsumer.subscribe({ topic: KAFKA_EVENTS_JSON })
        await kafkaEventsConsumer.run({
            eachMessage: ({ message }) => {
                kafkaEvents.push(message)
                return Promise.resolve()
            },
        })
    })

    afterAll(async () => {
        await kafkaEventsConsumer.disconnect()
    })

    beforeEach(async () => {
        kafkaEvents = []
        person = await hub.db.createPerson(
            DateTime.fromISO(timestamp).toUTC(),
            { foo: 'onPerson', pprop: 5 },
            {},
            {},
            2,
            null,
            false,
            personUuid,
            [{ distinctId: 'my_id' }]
        )
    })

    it('emits event with person columns, re-using event properties', async () => {
        const processPerson = true
        eventsProcessor.emitEvent(eventsProcessor.createEvent(preIngestionEvent, person, processPerson))

        await eventsProcessor.kafkaProducer.flush()

        // Waiting until we see the event in both Kafka nand ClickHouse
        const chEvents = await delayUntilEventIngested(() => (kafkaEvents.length ? hub.db.fetchEvents() : []))
        expect(kafkaEvents.length).toEqual(1)
        expect(JSON.parse(kafkaEvents[0].value!.toString())).toEqual(
            expect.objectContaining({
                uuid: eventUuid,
                event: '$pageview',
                team_id: 2,
                project_id: 1,
                distinct_id: 'my_id',
                person_id: personUuid,
            })
        )
        expect(chEvents.length).toEqual(1)
        expect(chEvents[0]).toEqual(
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
                person_mode: 'full',
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

        const processPerson = true
        eventsProcessor.emitEvent(
            eventsProcessor.createEvent(
                { ...preIngestionEvent, properties: { $group_0: 'group_key' } },
                person,
                processPerson
            )
        )

        const events = await delayUntilEventIngested(() => hub.db.fetchEvents())
        expect(events.length).toEqual(1)
        expect(events[0]).toEqual(
            expect.objectContaining({
                $group_0: 'group_key',
                $group_1: '',
                $group_2: '',
                $group_3: '',
                $group_4: '',
                person_mode: 'full',
            })
        )
    })

    it('when $process_person_profile=false, emits event with without person properties or groups', async () => {
        const processPerson = false
        eventsProcessor.emitEvent(
            eventsProcessor.createEvent(
                { ...preIngestionEvent, properties: { $group_0: 'group_key' } },
                person,
                processPerson
            )
        )

        await eventsProcessor.kafkaProducer.flush()

        const events = await delayUntilEventIngested(() => hub.db.fetchEvents())
        expect(events.length).toEqual(1)
        expect(events[0]).toEqual(
            expect.objectContaining({
                uuid: eventUuid,
                event: '$pageview',
                properties: {}, // $group_0 is removed
                timestamp: expect.any(DateTime),
                team_id: 2,
                distinct_id: 'my_id',
                elements_chain: null,
                created_at: expect.any(DateTime),
                person_id: personUuid,
                person_properties: {},
                person_mode: 'propertyless',
            })
        )
    })

    it('force_upgrade persons are recorded as such', async () => {
        const processPerson = false
        person.force_upgrade = true
        eventsProcessor.emitEvent(
            eventsProcessor.createEvent(
                { ...preIngestionEvent, properties: { $group_0: 'group_key' } },
                person,
                processPerson
            )
        )

        await eventsProcessor.kafkaProducer.flush()

        const events = await delayUntilEventIngested(() => hub.db.fetchEvents())
        expect(events.length).toEqual(1)
        expect(events[0]).toEqual(
            expect.objectContaining({
                uuid: eventUuid,
                event: '$pageview',
                properties: {}, // $group_0 is removed
                timestamp: expect.any(DateTime),
                team_id: 2,
                distinct_id: 'my_id',
                elements_chain: null,
                created_at: expect.any(DateTime),
                person_id: personUuid,
                person_properties: {},
                person_mode: 'force_upgrade',
            })
        )
    })

    it('handles the person no longer existing', async () => {
        // This person is never in the DB, but createEvent gets a Person object and should use that
        const uuid = new UUIDT().toString()
        const nonExistingPerson: Person = {
            created_at: DateTime.fromISO(timestamp).toUTC(),
            team_id: 0,
            properties: { random: 'x' },
            uuid: uuid,
        }
        const processPerson = true
        eventsProcessor.emitEvent(
            eventsProcessor.createEvent(
                { ...preIngestionEvent, distinctId: 'no-such-person' },
                nonExistingPerson,
                processPerson
            )
        )
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
