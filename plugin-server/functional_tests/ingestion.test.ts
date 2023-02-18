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

test.concurrent(`event ingestion: handles $groupidentify with no properties`, async () => {
    const teamId = await createTeam(postgres, organizationId)
    const distinctId = new UUIDT().toString()

    const groupIdentityUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, groupIdentityUuid, '$groupidentify', {
        distinct_id: distinctId,
        $group_type: 'organization',
        $group_key: 'posthog',
    })

    const firstEventUuid = new UUIDT().toString()
    await capture(producer, teamId, distinctId, firstEventUuid, 'custom event', {
        name: 'haha',
        $group_0: 'posthog',
    })

    const event = await waitForExpect(async () => {
        const [event] = await fetchEvents(clickHouseClient, teamId, firstEventUuid)
        expect(event).toBeDefined()
        return event
    })

    expect(event).toEqual(
        expect.objectContaining({
            $group_0: 'posthog',
            group0_properties: {},
        })
    )
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

test.concurrent(`event ingestion: initial login flow keeps the same person_id`, async () => {
    const teamId = await createTeam(postgres, organizationId)
    const initialDistinctId = 'initialDistinctId'
    const personIdentifier = 'test@posthog.com'

    // This simulates initial sign-up flow,
    // where the user has first been browsing the site anonymously for a while

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

    // We then identify the person
    await capture(producer, teamId, personIdentifier, new UUIDT().toString(), '$identify', {
        distinct_id: personIdentifier,
        $anon_distinct_id: initialDistinctId,
    })

    await waitForExpect(async () => {
        const events = await fetchEvents(clickHouseClient, teamId)
        expect(events.length).toBe(2)
        expect(events[0].person_id).toBeDefined()
        expect(events[0].person_id).not.toBe('00000000-0000-0000-0000-000000000000')
        expect(new Set(events.map((event) => event.person_id)).size).toBe(1)
    }, 10000)
})

const testIfPoEEmbraceJoinEnabled =
    process.env.POE_EMBRACE_JOIN_FOR_TEAMS === '*' ? test.concurrent : test.concurrent.skip
testIfPoEEmbraceJoinEnabled(`single merge results in all events resolving to the same person id`, async () => {
    const teamId = await createTeam(postgres, organizationId)
    const initialDistinctId = new UUIDT().toString()
    const secondDistinctId = new UUIDT().toString()
    const personIdentifier = new UUIDT().toString()

    // This simulates sign-up flow with backend events having an anonymous ID in both frontend and backend

    // First we emit anoymous events and wait for the persons to be created.
    const initialEventId = new UUIDT().toString()
    await capture(producer, teamId, initialDistinctId, initialEventId, 'custom event')
    const secondEventId = new UUIDT().toString()
    await capture(producer, teamId, secondDistinctId, secondEventId, 'custom event 2')
    await waitForExpect(async () => {
        const persons = await fetchPersons(clickHouseClient, teamId)
        expect(persons).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    properties: expect.objectContaining({ $creator_event_uuid: initialEventId }),
                }),
                expect.objectContaining({
                    properties: expect.objectContaining({ $creator_event_uuid: secondEventId }),
                }),
            ])
        )
    }, 10000)

    // Then we identify both ids
    const uuidOfFirstIdentifyEvent = new UUIDT().toString()
    await capture(producer, teamId, personIdentifier, uuidOfFirstIdentifyEvent, '$identify', {
        distinct_id: personIdentifier,
        $anon_distinct_id: initialDistinctId,
    })
    const uuidOfSecondIdentifyEvent = new UUIDT().toString()
    await capture(producer, teamId, personIdentifier, uuidOfSecondIdentifyEvent, '$identify', {
        distinct_id: personIdentifier,
        $anon_distinct_id: secondEventId,
    })

    await waitForExpect(async () => {
        const events = await fetchEvents(clickHouseClient, teamId)
        expect(events.length).toBe(4)
        expect(events[0].person_id).toBeDefined()
        expect(events[0].person_id).not.toBe('00000000-0000-0000-0000-000000000000')
        expect(new Set(events.map((event) => event.person_id)).size).toBe(1)
    }, 10000)
})

testIfPoEEmbraceJoinEnabled(`chained merge results in all events resolving to the same person id`, async () => {
    const teamId = await createTeam(postgres, organizationId)
    const initialDistinctId = new UUIDT().toString()
    const secondDistinctId = new UUIDT().toString()
    const thirdDistinctId = new UUIDT().toString()

    // First we emit anoymous events and wait for the persons to be created.
    await capture(producer, teamId, initialDistinctId, new UUIDT().toString(), 'custom event')
    await capture(producer, teamId, secondDistinctId, new UUIDT().toString(), 'custom event 2')
    await capture(producer, teamId, thirdDistinctId, new UUIDT().toString(), 'custom event 3')
    await waitForExpect(async () => {
        const persons = await fetchPersons(clickHouseClient, teamId)
        expect(persons.length).toBe(3)
    }, 10000)

    // Then we identify first two together
    await capture(producer, teamId, initialDistinctId, new UUIDT().toString(), '$identify', {
        distinct_id: initialDistinctId,
        $anon_distinct_id: secondDistinctId,
    })
    // Then we merge the third person
    await capture(producer, teamId, secondDistinctId, new UUIDT().toString(), '$identify', {
        distinct_id: secondDistinctId,
        $anon_distinct_id: thirdDistinctId,
    })

    await waitForExpect(async () => {
        const events = await fetchEvents(clickHouseClient, teamId)
        expect(events.length).toBe(5)
        expect(events[0].person_id).toBeDefined()
        expect(events[0].person_id).not.toBe('00000000-0000-0000-0000-000000000000')
        expect(new Set(events.map((event) => event.person_id)).size).toBe(1)
    }, 10000)
})

testIfPoEEmbraceJoinEnabled(
    `complex chained merge adds results in all events resolving to the same person id`,
    async () => {
        // let's assume we have 4 persons 1234, we'll first merge 1-2 & 3-4, then we'll merge 2-3
        // this should still result in all events having the same person_id or override[person_id]

        const teamId = await createTeam(postgres, organizationId)
        const initialDistinctId = new UUIDT().toString()
        const secondDistinctId = new UUIDT().toString()
        const thirdDistinctId = new UUIDT().toString()
        const forthDistinctId = new UUIDT().toString()

        // First we emit anoymous events and wait for the persons to be created.
        await capture(producer, teamId, initialDistinctId, new UUIDT().toString(), 'custom event')
        await capture(producer, teamId, secondDistinctId, new UUIDT().toString(), 'custom event 2')
        await capture(producer, teamId, thirdDistinctId, new UUIDT().toString(), 'custom event 3')
        await capture(producer, teamId, forthDistinctId, new UUIDT().toString(), 'custom event 3')
        await waitForExpect(async () => {
            const persons = await fetchPersons(clickHouseClient, teamId)
            expect(persons.length).toBe(4)
        }, 10000)

        // Then we identify 1-2 and 3-4
        await capture(producer, teamId, initialDistinctId, new UUIDT().toString(), '$identify', {
            distinct_id: initialDistinctId,
            $anon_distinct_id: secondDistinctId,
        })
        await capture(producer, teamId, thirdDistinctId, new UUIDT().toString(), '$identify', {
            distinct_id: thirdDistinctId,
            $anon_distinct_id: forthDistinctId,
        })

        await waitForExpect(async () => {
            const events = await fetchEvents(clickHouseClient, teamId)
            expect(events.length).toBe(6)
        }, 10000)

        // Then we merge 2-3
        // TODO: make this a valid merge event instead of $identify
        await capture(producer, teamId, initialDistinctId, new UUIDT().toString(), '$identify', {
            distinct_id: secondDistinctId,
            $anon_distinct_id: thirdDistinctId,
        })
        await waitForExpect(async () => {
            const events = await fetchEvents(clickHouseClient, teamId)
            expect(events.length).toBe(7)
            expect(events[0].person_id).toBeDefined()
            expect(events[0].person_id).not.toBe('00000000-0000-0000-0000-000000000000')
            expect(new Set(events.map((event) => event.person_id)).size).toBe(1)
        }, 10000)
    }
)

// TODO: adjust this test to poEEmbraceJoin
test.skip(`person properties don't see properties from descendents`, async () => {
    // The only thing that should propagate to an ancestor is the person_id.
    // Person properties should not propagate to ancestors within a branch.
    //
    //         P(k: v, set_once_property: value)
    //                        |
    //                        |
    //      P'(k: v, j: w, set_once_property: value)
    //
    // The person properties of P' should not be assiciated with events tied to
    // P.

    const teamId = await createTeam(postgres, organizationId)
    const firstDistinctId = new UUIDT().toString()

    const firstUuid = new UUIDT().toString()
    await capture(producer, teamId, firstDistinctId, firstUuid, 'custom event', {
        $set: {
            k: 'v',
        },
        $set_once: {
            set_once_property: 'value',
        },
    })

    const secondUuid = new UUIDT().toString()
    await capture(producer, teamId, firstDistinctId, secondUuid, 'custom event', {
        $set: {
            j: 'w',
        },
        $set_once: {
            set_once_property: 'second value',
        },
    })

    await waitForExpect(async () => {
        const [first] = await fetchEvents(clickHouseClient, teamId, firstUuid)
        const [second] = await fetchEvents(clickHouseClient, teamId, secondUuid)

        expect(first).toEqual(
            expect.objectContaining({
                person_id: second.person_id,
                person_properties: {
                    $creator_event_uuid: expect.any(String),
                    k: 'v',
                    set_once_property: 'value',
                },
            })
        )

        expect(second).toEqual(
            expect.objectContaining({
                person_properties: {
                    $creator_event_uuid: expect.any(String),
                    k: 'v',
                    j: 'w',
                    set_once_property: 'value',
                },
            })
        )
    })
})

// Skipping this test as without ording of events across distinct_id we don't
// know which event will be processed first, and hence this test is flaky. We
// are at any rate looking at alternatives to the implementation to speed up
// queries which may make this test obsolete.
test.skip(`person properties can't see properties from merge descendants`, async () => {
    // This is specifically to test that the merge event doesn't result in
    // properties being picked up on events from it's parents.
    //
    //             Alice(k: v)
    //                   \
    //                    \    Bob(j: w)
    //                     \   /
    //                      \ /
    //         AliceAndBob(k: v, j: w, l: x)
    //
    // NOTE: a stronger guarantee would be to ensure that events only pick up
    // properties from their relatives. Instead, if event e1 has a common
    // descendant with e2, they will pick up properties from which ever was
    // _processed_ first.
    // TODO: change the guarantee to be that unrelated branches properties are
    // isolated from each other.

    const teamId = await createTeam(postgres, organizationId)
    const aliceAnonId = new UUIDT().toString()
    const bobAnonId = new UUIDT().toString()

    const firstUuid = new UUIDT().toString()
    await capture(producer, teamId, aliceAnonId, firstUuid, 'custom event', {
        $set: {
            k: 'v',
        },
    })

    const secondUuid = new UUIDT().toString()
    await capture(producer, teamId, bobAnonId, secondUuid, 'custom event', {
        $set: {
            j: 'w',
        },
    })

    const thirdUuid = new UUIDT().toString()
    // NOTE: $create_alias is not symmetric, so we will currently get different
    // results according to the order of `bobAnonId` and `aliceAnonId`.
    // TODO: make $create_alias symmetric.
    await capture(producer, teamId, bobAnonId, thirdUuid, '$create_alias', {
        alias: aliceAnonId,
        $set: {
            l: 'x',
        },
    })

    // Now we wait to ensure that these events have been ingested.
    const [first, second, third] = await waitForExpect(async () => {
        const [first] = await fetchEvents(clickHouseClient, teamId, firstUuid)
        const [second] = await fetchEvents(clickHouseClient, teamId, secondUuid)
        const [third] = await fetchEvents(clickHouseClient, teamId, thirdUuid)

        expect(first).toBeDefined()
        expect(second).toBeDefined()
        expect(third).toBeDefined()

        return [first, second, third]
    })

    expect(first).toEqual(
        expect.objectContaining({
            person_id: third.person_id,
            person_properties: {
                $creator_event_uuid: expect.any(String),
                k: 'v',
            },
        })
    )

    expect(second).toEqual(
        expect.objectContaining({
            person_id: third.person_id,
            person_properties: {
                $creator_event_uuid: expect.any(String),
                k: 'v',
                j: 'w',
            },
        })
    )

    expect(third).toEqual(
        expect.objectContaining({
            person_properties: {
                $creator_event_uuid: expect.any(String),
                k: 'v',
                j: 'w',
                l: 'x',
            },
        })
    )
})
