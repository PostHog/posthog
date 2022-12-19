import ClickHouse from '@posthog/clickhouse'
import Redis from 'ioredis'
import { Kafka, Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'

import { defaultConfig } from '../src/config/config'
import { UUIDT } from '../src/utils/utils'
import { delayUntilEventIngested } from '../tests/helpers/clickhouse'
import { capture, createOrganization, createTeam, fetchEvents, fetchPersons, getMetric } from './api'
import { waitForExpect } from './expectations'

let producer: Producer
let clickHouseClient: ClickHouse
let postgres: Pool // NOTE: we use a Pool here but it's probably not necessary, but for instance `insertRow` uses a Pool.
let kafka: Kafka
let redis: Redis.Redis
let organizationId: string

beforeAll(async () => {
    // Setup connections to kafka, clickhouse, and postgres
    postgres = new Pool({
        connectionString: defaultConfig.DATABASE_URL!,
        // We use a pool only for typings sake, but we don't actually need to,
        // so set max connections to 1.
        max: 1,
    })
    clickHouseClient = new ClickHouse({
        host: defaultConfig.CLICKHOUSE_HOST,
        port: 8123,
        dataObjects: true,
        queryOptions: {
            database: defaultConfig.CLICKHOUSE_DATABASE,
            output_format_json_quote_64bit_integers: false,
        },
    })
    kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS] })
    producer = kafka.producer({ createPartitioner: Partitioners.DefaultPartitioner })
    await producer.connect()
    redis = new Redis(defaultConfig.REDIS_URL)

    organizationId = await createOrganization(postgres)
})

afterAll(async () => {
    await Promise.all([producer.disconnect(), postgres.end(), redis.disconnect()])
})

test.concurrent(`event ingestion: can set and update group properties`, async () => {
    const teamId = await createTeam(postgres, organizationId)
    const distinctId = new UUIDT().toString()

    const groupIdentityUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, groupIdentityUuid, '$groupidentify', {
        distinct_id: distinctId,
        $group_type: 'organization',
        $group_key: 'posthog',
        $group_set: {
            prop: 'value',
        },
    })

    const [firstGroupIdentity] = await delayUntilEventIngested(
        () => fetchEvents(clickHouseClient, teamId, groupIdentityUuid),
        1,
        500,
        40
    )
    expect(firstGroupIdentity.event).toBeDefined()

    const firstEventUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, firstEventUuid, 'custom event', {
        name: 'haha',
        $group_0: 'posthog',
    })
    const [firstEvent] = await delayUntilEventIngested(
        () => fetchEvents(clickHouseClient, teamId, firstEventUuid),
        1,
        500,
        40
    )
    expect(firstEvent).toEqual(
        expect.objectContaining({
            $group_0: 'posthog',
            group0_properties: {
                prop: 'value',
            },
        })
    )

    const secondGroupIdentityUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, secondGroupIdentityUuid, '$groupidentify', {
        distinct_id: distinctId,
        $group_type: 'organization',
        $group_key: 'posthog',
        $group_set: {
            prop: 'updated value',
        },
    })

    const [secondGroupIdentity] = await delayUntilEventIngested(
        () => fetchEvents(clickHouseClient, teamId, secondGroupIdentityUuid),
        1,
        500,
        40
    )
    expect(secondGroupIdentity).toBeDefined()

    const secondEventUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, secondEventUuid, 'custom event', {
        name: 'haha',
        $group_0: 'posthog',
    })
    const [event] = await delayUntilEventIngested(
        () => fetchEvents(clickHouseClient, teamId, secondEventUuid),
        1,
        500,
        40
    )
    expect(event).toEqual(
        expect.objectContaining({
            $group_0: 'posthog',
            group0_properties: {
                prop: 'updated value',
            },
        })
    )
})

test.concurrent(`event ingestion: can $set and update person properties`, async () => {
    const teamId = await createTeam(postgres, organizationId)
    const distinctId = new UUIDT().toString()
    const personEventUuid = new UUIDT().toString()

    await capture(producer, teamId, distinctId, personEventUuid, '$identify', {
        distinct_id: distinctId,
        $set: { prop: 'value' },
    })

    const firstUuid = new UUIDT().toString()

    await capture(producer, teamId, distinctId, firstUuid, 'custom event', {})

    const [firstEvent] = await delayUntilEventIngested(
        () => fetchEvents(clickHouseClient, teamId, firstUuid),
        1,
        500,
        40
    )
    expect(firstEvent).toEqual(
        expect.objectContaining({
            person_properties: {
                $creator_event_uuid: personEventUuid,
                prop: 'value',
            },
        })
    )

    await capture(producer, teamId, distinctId, personEventUuid, '$identify', {
        distinct_id: distinctId,
        $set: { prop: 'updated value' },
    })

    const secondUuid = new UUIDT().toString()

    await capture(producer, teamId, distinctId, secondUuid, 'custom event', {})

    const [secondEvent] = await delayUntilEventIngested(
        () => fetchEvents(clickHouseClient, teamId, secondUuid),
        1,
        500,
        40
    )
    expect(secondEvent).toEqual(
        expect.objectContaining({
            person_properties: {
                $creator_event_uuid: personEventUuid,
                prop: 'updated value',
            },
        })
    )
})

test.concurrent(`event ingestion: can $set_once person properties but not update`, async () => {
    const teamId = await createTeam(postgres, organizationId)
    const distinctId = new UUIDT().toString()

    const personEventUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, personEventUuid, '$identify', {
        distinct_id: distinctId,
        $set_once: { prop: 'value' },
    })

    const firstUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, firstUuid, 'custom event', {})

    const [firstEvent] = await delayUntilEventIngested(
        () => fetchEvents(clickHouseClient, teamId, firstUuid),
        1,
        500,
        40
    )
    expect(firstEvent).toEqual(
        expect.objectContaining({
            person_properties: {
                $creator_event_uuid: personEventUuid,
                prop: 'value',
            },
        })
    )

    await capture(producer, teamId, distinctId, personEventUuid, '$identify', {
        distinct_id: distinctId,
        $set_once: { prop: 'updated value' },
    })

    const secondUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, secondUuid, 'custom event', {})

    const [secondEvent] = await delayUntilEventIngested(
        () => fetchEvents(clickHouseClient, teamId, secondUuid),
        1,
        500,
        40
    )
    expect(secondEvent).toEqual(
        expect.objectContaining({
            person_properties: {
                $creator_event_uuid: personEventUuid,
                prop: 'value',
            },
        })
    )
})

test.concurrent(
    `event ingestion: anonymous event recieves same person_id if $identify happenes shortly after`,
    async () => {
        // NOTE: this test depends on there being a delay between the
        // anonymouse event ingestion and the processing of this event.
        const teamId = await createTeam(postgres, organizationId)
        const initialDistinctId = 'initialDistinctId'
        const returningDistinctId = 'returningDistinctId'
        const personIdentifier = 'test@posthog.com'

        // First we identify the user using an initial distinct id. After
        // which we capture an event with a different distinct id, then
        // identify this user again with the same person identifier.
        //
        // This is to simulate the case where:
        //
        //  1. user signs up initially, creating a person
        //  2. user returns but as an anonymous user, capturing events
        //  3. user identifies themselves, for instance by logging in
        //
        // In this case we want to end up with on Person to which all the
        // events are associated.

        await capture(producer, teamId, personIdentifier, new UUIDT().toString(), '$identify', {
            distinct_id: personIdentifier,
            $anon_distinct_id: initialDistinctId,
        })

        await capture(producer, teamId, returningDistinctId, new UUIDT().toString(), 'custom event', {
            name: 'hehe',
            uuid: new UUIDT().toString(),
        })

        await new Promise((resolve) => setTimeout(resolve, 100))

        await capture(producer, teamId, personIdentifier, new UUIDT().toString(), '$identify', {
            distinct_id: personIdentifier,
            $anon_distinct_id: returningDistinctId,
        })

        const events = await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 3, 500, 40)
        expect(events.length).toBe(3)
        expect(new Set(events.map((event) => event.person_id)).size).toBe(1)

        await delayUntilEventIngested(() => fetchPersons(clickHouseClient, teamId), 1, 500, 40)
        const persons = await fetchPersons(clickHouseClient, teamId)
        expect(persons.length).toBe(1)
    }
)

test.concurrent(`event ingestion: events without a team_id get processed correctly`, async () => {
    const token = new UUIDT().toString()
    const teamId = await createTeam(postgres, organizationId, '', token)
    const personIdentifier = 'test@posthog.com'

    await capture(
        producer,
        null, // team_id should be added by the plugin server from the token
        personIdentifier,
        new UUIDT().toString(),
        'test event',
        {
            distinct_id: personIdentifier,
        },
        token
    )

    const events = await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 1, 500, 40)
    expect(events.length).toBe(1)
    expect(events[0].team_id).toBe(teamId)
})

test.concurrent('consumer updates timestamp exported to prometheus', async () => {
    // NOTE: it may be another event other than the one we emit here that causes
    // the gauge to increase, but pushing this event through should at least
    // ensure that the gauge is updated.
    const teamId = await createTeam(postgres, organizationId)
    const distinctId = new UUIDT().toString()

    const metricBefore = await getMetric({
        name: 'latest_processed_timestamp_ms',
        type: 'GAUGE',
        labels: { topic: 'events_plugin_ingestion', partition: '0', groupId: 'ingestion' },
    })

    await capture(producer, teamId, distinctId, new UUIDT().toString(), 'custom event', {})

    await waitForExpect(async () => {
        const metricAfter = await getMetric({
            name: 'latest_processed_timestamp_ms',
            type: 'GAUGE',
            labels: { topic: 'events_plugin_ingestion', partition: '0', groupId: 'ingestion' },
        })
        expect(metricAfter).toBeGreaterThan(metricBefore)
        expect(metricAfter).toBeLessThan(Date.now()) // Make sure, e.g. we're not setting micro seconds
        expect(metricAfter).toBeGreaterThan(Date.now() - 60_000) // Make sure, e.g. we're not setting seconds
    })
})
