import ClickHouse from '@posthog/clickhouse'
import Redis from 'ioredis'
import { Kafka, Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'

import { defaultConfig } from '../src/config/config'
import { UUIDT } from '../src/utils/utils'
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

    const firstEventUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, firstEventUuid, 'custom event', {
        name: 'haha',
        $group_0: 'posthog',
    })

    await waitForExpect(async () => {
        const [event] = await fetchEvents(clickHouseClient, teamId, firstEventUuid)
        expect(event).toEqual(
            expect.objectContaining({
                $group_0: 'posthog',
                group0_properties: {
                    prop: 'value',
                },
            })
        )
    })

    const secondGroupIdentityUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, secondGroupIdentityUuid, '$groupidentify', {
        distinct_id: distinctId,
        $group_type: 'organization',
        $group_key: 'posthog',
        $group_set: {
            prop: 'updated value',
        },
    })

    const secondEventUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, secondEventUuid, 'custom event', {
        name: 'haha',
        $group_0: 'posthog',
    })
    await waitForExpect(async () => {
        const [event] = await fetchEvents(clickHouseClient, teamId, secondEventUuid)
        expect(event).toEqual(
            expect.objectContaining({
                $group_0: 'posthog',
                group0_properties: {
                    prop: 'updated value',
                },
            })
        )
    })
})

test.concurrent(`event ingestion: can $set and update person properties`, async () => {
    const teamId = await createTeam(postgres, organizationId)
    const distinctId = new UUIDT().toString()

    await capture(producer, teamId, distinctId, new UUIDT().toString(), '$identify', {
        distinct_id: distinctId,
        $set: { prop: 'value' },
    })

    const firstUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, firstUuid, 'custom event', {})
    await waitForExpect(async () => {
        const [event] = await fetchEvents(clickHouseClient, teamId, firstUuid)
        expect(event).toEqual(
            expect.objectContaining({
                person_properties: expect.objectContaining({
                    prop: 'value',
                }),
            })
        )
    })

    await capture(producer, teamId, distinctId, new UUIDT().toString(), '$identify', {
        distinct_id: distinctId,
        $set: { prop: 'updated value' },
    })

    const secondUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, secondUuid, 'custom event', {})
    await waitForExpect(async () => {
        const [event] = await fetchEvents(clickHouseClient, teamId, secondUuid)
        expect(event).toEqual(
            expect.objectContaining({
                person_properties: expect.objectContaining({
                    prop: 'updated value',
                }),
            })
        )
    })
})

test.concurrent(`event ingestion: person properties are point in event time`, async () => {
    const teamId = await createTeam(postgres, organizationId)
    const distinctId = new UUIDT().toString()

    await capture(producer, teamId, distinctId, new UUIDT().toString(), '$identify', {
        distinct_id: distinctId,
        $set: { prop: 'value' },
    })

    const firstUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, firstUuid, 'custom event', {})
    await capture(producer, teamId, distinctId, new UUIDT().toString(), 'custom event', {
        distinct_id: distinctId,
        $set: {
            prop: 'updated value', // This value should not be reflected in the first event
            new_prop: 'new value', // This new value should be reflected in the first event
        },
    })

    await waitForExpect(async () => {
        const [event] = await fetchEvents(clickHouseClient, teamId, firstUuid)
        expect(event).toEqual(
            expect.objectContaining({
                person_properties: expect.objectContaining({
                    prop: 'value',
                }),
            })
        )
    })
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
    await waitForExpect(async () => {
        const [event] = await fetchEvents(clickHouseClient, teamId, firstUuid)
        expect(event).toEqual(
            expect.objectContaining({
                person_properties: {
                    $creator_event_uuid: personEventUuid,
                    prop: 'value',
                },
            })
        )
    })

    await capture(producer, teamId, distinctId, personEventUuid, '$identify', {
        distinct_id: distinctId,
        $set_once: { prop: 'updated value' },
    })

    const secondUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, secondUuid, 'custom event', {})
    await waitForExpect(async () => {
        const [event] = await fetchEvents(clickHouseClient, teamId, secondUuid)
        expect(event).toEqual(
            expect.objectContaining({
                person_properties: {
                    $creator_event_uuid: personEventUuid,
                    prop: 'value',
                },
            })
        )
    })
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

        await capture(producer, teamId, personIdentifier, new UUIDT().toString(), '$identify', {
            distinct_id: personIdentifier,
            $anon_distinct_id: returningDistinctId,
        })

        await waitForExpect(async () => {
            const events = await fetchEvents(clickHouseClient, teamId)
            expect(events.length).toBe(3)
            expect(new Set(events.map((event) => event.person_id)).size).toBe(1)
        }, 10000)
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

    await waitForExpect(async () => {
        const events = await fetchEvents(clickHouseClient, teamId)
        expect(events.length).toBe(1)
        expect(events[0].team_id).toBe(teamId)
    })
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
    }, 10_000)
})

// We only want to run these test if we are running with the delay all events
// feature enabled. See https://github.com/PostHog/product-internal/pull/405 for
// details.
const testIfDelayEnabled = process.env.DELAY_ALL_EVENTS_FOR_TEAMS === '*' ? test.concurrent : test.concurrent.skip
testIfDelayEnabled(
    `anonymous event recieves same person_id if $identify happenes shortly after, and there's already an anonymous person`,
    async () => {
        const teamId = await createTeam(postgres, organizationId)
        const initialDistinctId = new UUIDT().toString()
        const secondDistinctId = new UUIDT().toString()
        const personIdentifier = new UUIDT().toString()

        // First we emit an anoymous event and wait for the person to be
        // created.
        const initialEventId = new UUIDT().toString()
        await capture(producer, teamId, initialDistinctId, initialEventId, 'custom event')
        await waitForExpect(async () => {
            const persons = await fetchPersons(clickHouseClient, teamId)
            expect(persons).toContainEqual(
                expect.objectContaining({
                    properties: expect.objectContaining({ $creator_event_uuid: initialEventId }),
                })
            )
        }, 10000)

        // We then have the user identify themselves, but on e.g. a different
        // device and hence a different anonymous id.
        const initialIdentifyEventId = new UUIDT().toString()
        await capture(producer, teamId, personIdentifier, initialIdentifyEventId, '$identify', {
            $anon_distinct_id: secondDistinctId,
            distinct_id: personIdentifier,
        })
        await waitForExpect(async () => {
            const persons = await fetchPersons(clickHouseClient, teamId)
            expect(persons).toContainEqual(
                expect.objectContaining({
                    properties: expect.objectContaining({ $creator_event_uuid: initialIdentifyEventId }),
                })
            )
        }, 10000)

        // Then we create another event with the initial anonymous distinct id,
        // shortly followed by another identify event but this time with the
        // initial anonymous distinct id
        const uuidOfEventThatShouldBeIdentified = new UUIDT().toString()
        await capture(producer, teamId, initialDistinctId, uuidOfEventThatShouldBeIdentified, 'custom event')

        const uuidOfIdentifyEvent = new UUIDT().toString()
        await capture(producer, teamId, personIdentifier, uuidOfIdentifyEvent, '$identify', {
            distinct_id: personIdentifier,
            $anon_distinct_id: initialDistinctId,
        })

        await waitForExpect(async () => {
            const [anonymousEvent] = await fetchEvents(clickHouseClient, teamId, uuidOfEventThatShouldBeIdentified)
            const [identifyEvent] = await fetchEvents(clickHouseClient, teamId, uuidOfIdentifyEvent)
            expect(anonymousEvent?.person_id).toBeDefined()
            expect(identifyEvent?.person_id).toBeDefined()
            expect(anonymousEvent.person_id).toEqual(identifyEvent.person_id)
        }, 10000)
    }
)

testIfDelayEnabled(`events reference same person_id if two people merged shortly after`, async () => {
    const teamId = await createTeam(postgres, organizationId)
    const firstDistinctId = new UUIDT().toString()
    const secondDistinctId = new UUIDT().toString()
    const firstPersonIdentity = new UUIDT().toString()
    const secondPersonIdentity = new UUIDT().toString()

    const initialEventId = new UUIDT().toString()
    await capture(producer, teamId, firstDistinctId, initialEventId, 'custom event')

    const secondEventId = new UUIDT().toString()
    await capture(producer, teamId, secondDistinctId, secondEventId, 'custom event')

    // First create two people with nothing in common
    await capture(producer, teamId, firstPersonIdentity, new UUIDT().toString(), '$identify', {
        $anon_distinct_id: firstDistinctId,
        distinct_id: firstPersonIdentity,
    })

    await capture(producer, teamId, secondPersonIdentity, new UUIDT().toString(), '$identify', {
        $anon_distinct_id: secondDistinctId,
        distinct_id: firstPersonIdentity,
    })

    // Then merge them together immediately such that this event is within the
    // delay window.
    await capture(producer, teamId, firstPersonIdentity, new UUIDT().toString(), '$create_alias', {
        alias: secondPersonIdentity,
    })

    await waitForExpect(async () => {
        const [secondEvent] = await fetchEvents(clickHouseClient, teamId, secondEventId)
        const [initialEvent] = await fetchEvents(clickHouseClient, teamId, initialEventId)
        expect(secondEvent?.person_id).toBeDefined()
        expect(secondEvent.person_id).toEqual(initialEvent.person_id)
    }, 10000)
})

testIfDelayEnabled(`person properties are ordered even for identify events`, async () => {
    // This test is specifically to validate that for the case where we set
    // properties via a custom event, then via an identify event, the properties
    // are ordered correctly. This is important because with the initial
    // implementation of the delay for Person-on-Events we would treat identify
    // events specially, and it would fail with that implementation.

    const teamId = await createTeam(postgres, organizationId)
    const firstDistinctId = new UUIDT().toString()
    const secondDistinctId = new UUIDT().toString()
    const personIdentifier = new UUIDT().toString()

    const firstUuid = new UUIDT().toString()
    await capture(producer, teamId, firstDistinctId, firstUuid, 'custom event', {
        $set: {
            prop: 'value',
        },
        $set_once: {
            set_once_property: 'value',
        },
    })

    const secondUuid = new UUIDT().toString()
    await capture(producer, teamId, secondDistinctId, secondUuid, 'custom event', {
        $set: {
            prop: 'second value',
        },
        $set_once: {
            set_once_property: 'second value',
        },
    })

    const thirdUuid = new UUIDT().toString()
    await capture(producer, teamId, personIdentifier, thirdUuid, '$identify', {
        distinct_id: personIdentifier,
        $anon_distinct_id: firstDistinctId,
        $set: {
            prop: 'identify value',
        },
        $set_once: {
            set_once_property: 'identify value',
        },
    })

    const forthUuid = new UUIDT().toString()
    await capture(producer, teamId, personIdentifier, forthUuid, '$identify', {
        distinct_id: personIdentifier,
        $anon_distinct_id: secondDistinctId,
        $set: {
            prop: 'second identify value',
        },
        $set_once: {
            set_once_property: 'second identify value',
        },
    })

    await waitForExpect(async () => {
        const [first] = await fetchEvents(clickHouseClient, teamId, firstUuid)
        const [second] = await fetchEvents(clickHouseClient, teamId, secondUuid)
        const [third] = await fetchEvents(clickHouseClient, teamId, thirdUuid)
        const [forth] = await fetchEvents(clickHouseClient, teamId, forthUuid)

        expect(first).toEqual(
            expect.objectContaining({
                person_id: forth.person_id,
                person_properties: expect.objectContaining({
                    prop: 'value',
                    set_once_property: 'value',
                }),
            })
        )

        expect(second).toEqual(
            expect.objectContaining({
                person_id: forth.person_id,
                person_properties: expect.objectContaining({
                    prop: 'second value',
                    set_once_property: 'value',
                }),
            })
        )

        expect(third).toEqual(
            expect.objectContaining({
                person_id: forth.person_id,
                person_properties: expect.objectContaining({
                    prop: 'identify value',
                    set_once_property: 'value',
                }),
            })
        )

        expect(forth).toEqual(
            expect.objectContaining({
                person_properties: expect.objectContaining({
                    prop: 'second identify value',
                    set_once_property: 'value',
                }),
            })
        )
    })
})

testIfDelayEnabled(
    `person properties as per https://github.com/PostHog/posthog/pull/13505#discussion_r1061675265`,
    async () => {
        const teamId = await createTeam(postgres, organizationId)
        const aliceAnonId = new UUIDT().toString()
        const bobAnonId = new UUIDT().toString()
        const bobId = new UUIDT().toString()

        const firstUuid = new UUIDT().toString()
        await capture(producer, teamId, aliceAnonId, firstUuid, 'custom event', {
            $set: {
                k: 'v1',
            },
        })

        const secondUuid = new UUIDT().toString()
        await capture(producer, teamId, bobId, secondUuid, '$identify', {
            $anon_distinct_id: bobAnonId,
            $set: {
                k: 'v2',
            },
        })

        // Now we wait to ensure that these events have been ingested.
        const [first, second] = await waitForExpect(async () => {
            const [first] = await fetchEvents(clickHouseClient, teamId, firstUuid)
            const [second] = await fetchEvents(clickHouseClient, teamId, secondUuid)

            expect(first).toBeDefined()
            expect(second).toBeDefined()

            return [first, second]
        })

        const thirdUuid = new UUIDT().toString()
        await capture(producer, teamId, bobId, thirdUuid, 'custom event', {
            $set: {
                k: 'v3',
            },
        })

        const forthUuid = new UUIDT().toString()
        // NOTE: this test doesn't work if we switch around `bobAnonId` and
        // `aliceAnonId`
        await capture(producer, teamId, bobAnonId, forthUuid, '$create_alias', {
            alias: aliceAnonId,
        })

        const [third, forth] = await waitForExpect(async () => {
            const [third] = await fetchEvents(clickHouseClient, teamId, thirdUuid)
            const [forth] = await fetchEvents(clickHouseClient, teamId, forthUuid)

            expect(third).toBeDefined()
            expect(forth).toBeDefined()

            return [third, forth]
        })

        expect(first).toEqual(
            expect.objectContaining({
                person_properties: expect.objectContaining({
                    k: 'v1',
                }),
            })
        )

        expect(second).toEqual(
            expect.objectContaining({
                person_properties: expect.objectContaining({
                    k: 'v2',
                }),
            })
        )

        expect(third).toEqual(
            expect.objectContaining({
                person_id: forth.person_id,
                person_properties: expect.objectContaining({
                    k: 'v3',
                }),
            })
        )

        expect(forth).toEqual(
            expect.objectContaining({
                person_properties: expect.objectContaining({
                    k: 'v3',
                }),
            })
        )
    }
)
