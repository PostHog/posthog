import * as IORedis from 'ioredis'
import { DateTime } from 'luxon'

import { Hub, ISOTimestamp, PreIngestionEvent } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { LazyPersonContainer } from '../../../src/worker/ingestion/lazy-person-container'
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
    let personContainer: LazyPersonContainer

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
        properties: { event: 'property' },
        elementsList: [],
    }

    beforeEach(() => {
        personContainer = new LazyPersonContainer(2, 'my_id', hub, {
            uuid: personUuid,
            properties: { foo: 'bar' },
            team_id: 1,
            id: 1,
            created_at: DateTime.fromISO(timestamp).toUTC(),
        } as any)
    })

    it('emits event with person columns, re-using event properties', async () => {
        jest.spyOn(eventsProcessor.db, 'getPersonData')

        const result = await eventsProcessor.createEvent(preIngestionEvent, personContainer)

        await eventsProcessor.kafkaProducer.flush()

        const events = await delayUntilEventIngested(() => hub.db.fetchEvents())
        expect(events.length).toEqual(1)
        expect(events[0]).toEqual(
            expect.objectContaining({
                uuid: eventUuid,
                event: '$pageview',
                properties: { event: 'property' },
                timestamp: expect.any(DateTime),
                team_id: 2,
                distinct_id: 'my_id',
                elements_chain: null,
                created_at: expect.any(DateTime),
                person_id: personUuid,
                person_properties: { foo: 'bar' },
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
        expect(result).toEqual(preIngestionEvent)
        expect(jest.mocked(eventsProcessor.db.getPersonData)).not.toHaveBeenCalled()
    })

    it('emits event with group columns', async () => {
        await eventsProcessor.db.insertGroup(2, 0, 'group_key', { group_prop: 'value' }, DateTime.fromISO(timestamp), 1)

        await eventsProcessor.createEvent(
            { ...preIngestionEvent, properties: { $group_0: 'group_key' } },
            personContainer
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

    it('emits event with person columns if not previously fetched', async () => {
        jest.spyOn(eventsProcessor.db, 'getPersonData')
        await eventsProcessor.db.createPerson(
            DateTime.fromISO(timestamp).toUTC(),
            { foo: 'bar', a: 2 },
            2,
            null,
            false,
            personUuid,
            ['my_id']
        )

        await eventsProcessor.createEvent(
            {
                ...preIngestionEvent,
                properties: { $set: { a: 1 } },
            },
            // :TRICKY: We pretend the person has been updated in-between processing and creating the event
            new LazyPersonContainer(2, 'my_id', hub)
        )

        await eventsProcessor.kafkaProducer.flush()

        const events = await delayUntilEventIngested(() => hub.db.fetchEvents())
        expect(events.length).toEqual(1)
        expect(events[0]).toEqual(
            expect.objectContaining({
                uuid: eventUuid,
                distinct_id: 'my_id',
                person_id: personUuid,
                person_properties: { foo: 'bar', a: 1 },
            })
        )
    })

    it('handles the person no longer existing', async () => {
        await eventsProcessor.createEvent(preIngestionEvent, new LazyPersonContainer(2, 'my_id', hub))
        await eventsProcessor.kafkaProducer.flush()

        const events = await delayUntilEventIngested(() => hub.db.fetchEvents())
        expect(events.length).toEqual(1)
        expect(events[0]).toEqual(
            expect.objectContaining({
                uuid: eventUuid,
                distinct_id: 'my_id',
                person_id: '00000000-0000-0000-0000-000000000000',
                person_properties: {},
            })
        )
    })
})
