/*
This file contains a bunch of legacy E2E tests mixed with unit tests.

Rather than add tests here, consider improving event-pipeline-integration test suite or adding
unit tests to appropriate classes/functions.
*/

import { Properties } from '@posthog/plugin-scaffold'
import { PluginEvent } from '@posthog/plugin-scaffold/src/types'
import * as IORedis from 'ioredis'
import { DateTime } from 'luxon'

import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../src/config/kafka-topics'
import {
    Database,
    Event,
    Hub,
    LogLevel,
    Person,
    PluginsServerConfig,
    PropertyType,
    PropertyUpdateOperation,
    Team,
} from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { personInitialAndUTMProperties } from '../../src/utils/db/utils'
import { posthog } from '../../src/utils/posthog'
import { UUIDT } from '../../src/utils/utils'
import { EventPipelineRunner } from '../../src/worker/ingestion/event-pipeline/runner'
import { EventsProcessor } from '../../src/worker/ingestion/process-event'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../helpers/clickhouse'
import { resetKafka } from '../helpers/kafka'
import { createUserTeamAndOrganization, getFirstTeam, getTeams, resetTestDatabase } from '../helpers/sql'

jest.mock('../../src/utils/status')
jest.setTimeout(600000) // 600 sec timeout.

export async function createPerson(
    server: Hub,
    team: Team,
    distinctIds: string[],
    properties: Record<string, any> = {}
): Promise<Person> {
    return server.db.createPerson(
        DateTime.utc(),
        properties,
        {},
        {},
        team.id,
        null,
        false,
        new UUIDT().toString(),
        distinctIds
    )
}

export type ReturnWithHub = { hub?: Hub; closeHub?: () => Promise<void> }

type EventsByPerson = [string[], string[]]

export const getEventsByPerson = async (hub: Hub): Promise<EventsByPerson[]> => {
    // Helper function to retrieve events paired with their associated distinct
    // ids
    const persons = await hub.db.fetchPersons()
    const events = await hub.db.fetchEvents()

    return await Promise.all(
        persons.map(async (person) => {
            const distinctIds = await hub.db.fetchDistinctIdValues(person)

            return [
                distinctIds,
                (events as Event[])
                    .filter((event) => distinctIds.includes(event.distinct_id))
                    .sort((e1, e2) => new Date(e1.timestamp).getTime() - new Date(e2.timestamp).getTime())
                    .map((event) => event.event),
            ] as EventsByPerson
        })
    )
}

const TEST_CONFIG: Partial<PluginsServerConfig> = {
    LOG_LEVEL: LogLevel.Log,
    KAFKA_CONSUMPTION_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,
}

let processEventCounter = 0
let mockClientEventCounter = 0
let team: Team
let hub: Hub
let closeHub: () => Promise<void>
let redis: IORedis.Redis
let eventsProcessor: EventsProcessor
let now = DateTime.utc()

async function createTestHub(additionalProps?: Record<string, any>): Promise<[Hub, () => Promise<void>]> {
    const [hub, closeHub] = await createHub({
        ...TEST_CONFIG,
        ...(additionalProps ?? {}),
    })

    redis = await hub.redisPool.acquire()

    return [hub, closeHub]
}

async function processEvent(
    distinctId: string,
    ip: string | null,
    _siteUrl: string,
    data: Partial<PluginEvent>,
    teamId: number,
    timestamp: DateTime,
    eventUuid: string
): Promise<void> {
    const pluginEvent: PluginEvent = {
        distinct_id: distinctId,
        site_url: _siteUrl,
        team_id: teamId,
        timestamp: timestamp.toUTC().toISO(),
        now: timestamp.toUTC().toISO(),
        ip: ip,
        uuid: eventUuid,
        ...data,
    } as any as PluginEvent

    const runner = new EventPipelineRunner(hub, pluginEvent)
    await runner.runEventPipeline(pluginEvent)

    await delayUntilEventIngested(() => hub.db.fetchEvents(), ++processEventCounter)
}

// Simple client used to simulate sending events
// Use state object to simulate stateful clients that keep track of old
// distinct id, starting with an anonymous one. I've taken posthog-js as
// the reference implementation.
let state = { currentDistinctId: 'anonymous_id' }

beforeAll(async () => {
    await resetKafka(TEST_CONFIG)
})

beforeEach(async () => {
    const testCode = `
            function processEvent (event, meta) {
                event.properties["somewhere"] = "over the rainbow";
                return event
            }
        `
    await resetTestDatabase(testCode, TEST_CONFIG)
    await resetTestDatabaseClickhouse(TEST_CONFIG)
    ;[hub, closeHub] = await createTestHub()
    eventsProcessor = new EventsProcessor(hub)
    processEventCounter = 0
    mockClientEventCounter = 0
    team = await getFirstTeam(hub)
    now = DateTime.utc()

    // clear the webhook redis cache
    const hooksCacheKey = `@posthog/plugin-server/hooks/${team.id}`
    await redis.del(hooksCacheKey)

    // Always start with an anonymous state
    state = { currentDistinctId: 'anonymous_id' }
})

afterEach(async () => {
    await hub.redisPool.release(redis)
    await closeHub?.()
})

const capture = async (hub: Hub, eventName: string, properties: any = {}) => {
    const event = {
        event: eventName,
        distinct_id: properties.distinct_id ?? state.currentDistinctId,
        properties: properties,
        now: new Date().toISOString(),
        sent_at: new Date().toISOString(),
        ip: '127.0.0.1',
        site_url: 'https://posthog.com',
        team_id: team.id,
        uuid: new UUIDT().toString(),
    }
    const runner = new EventPipelineRunner(hub, event)
    await runner.runEventPipeline(event)
    await delayUntilEventIngested(() => hub.db.fetchEvents(), ++mockClientEventCounter)
}

const identify = async (hub: Hub, distinctId: string) => {
    // Update currentDistinctId state immediately, as the event will be
    // dispatch asynchronously
    const currentDistinctId = state.currentDistinctId
    state.currentDistinctId = distinctId
    await capture(hub, '$identify', {
        // posthog-js will send the previous distinct id as
        // $anon_distinct_id
        $anon_distinct_id: currentDistinctId,
        distinct_id: distinctId,
    })
}

const alias = async (hub: Hub, alias: string, distinctId: string) => {
    await capture(hub, '$create_alias', { alias, disinct_id: distinctId })
}

test('merge people', async () => {
    const p0 = await createPerson(hub, team, ['person_0'], { $os: 'Microsoft' })
    await delayUntilEventIngested(() => hub.db.fetchPersons(Database.ClickHouse), 1)

    await hub.db.updatePersonDeprecated(p0, { created_at: DateTime.fromISO('2020-01-01T00:00:00Z') })

    const p1 = await createPerson(hub, team, ['person_1'], { $os: 'Chrome', $browser: 'Chrome' })
    await delayUntilEventIngested(() => hub.db.fetchPersons(Database.ClickHouse), 2)
    await hub.db.updatePersonDeprecated(p1, { created_at: DateTime.fromISO('2019-07-01T00:00:00Z') })

    await processEvent(
        'person_1',
        '',
        '',
        {
            event: 'user signed up',
            properties: {},
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchPersons()).length).toEqual(2)

    await delayUntilEventIngested(() => hub.db.fetchPersons(Database.ClickHouse), 2)
    const chPeople = await hub.db.fetchPersons(Database.ClickHouse)
    expect(chPeople.length).toEqual(2)

    await processEvent(
        'person_0',
        '',
        '',
        {
            event: '$identify',
            properties: { $anon_distinct_id: 'person_1' },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    await delayUntilEventIngested(async () =>
        (await hub.db.fetchPersons(Database.ClickHouse)).length === 1 ? [1] : []
    )
    expect((await hub.db.fetchPersons(Database.ClickHouse)).length).toEqual(1)

    const [person] = await hub.db.fetchPersons()

    expect(person.properties).toEqual({ $os: 'Microsoft', $browser: 'Chrome' })
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['person_0', 'person_1'])
    expect(person.created_at.toISO()).toEqual(DateTime.fromISO('2019-07-01T00:00:00Z').setZone('UTC').toISO())
})

test('capture new person', async () => {
    await hub.db.postgresQuery(
        `UPDATE posthog_team
             SET ingested_event = $1
             WHERE id = $2`,
        [true, team.id],
        'testTag'
    )
    team = await getFirstTeam(hub)

    expect(await hub.db.fetchEventDefinitions()).toEqual([])
    expect(await hub.db.fetchPropertyDefinitions()).toEqual([])

    const properties = personInitialAndUTMProperties({
        distinct_id: 2,
        token: team.api_token,
        $browser: 'Chrome',
        $current_url: 'https://test.com',
        $os: 'Mac OS X',
        $browser_version: '95',
        $initial_referring_domain: 'https://google.com',
        $initial_referrer_url: 'https://google.com/?q=posthog',
        utm_medium: 'twitter',
        gclid: 'GOOGLE ADS ID',
        $elements: [
            { tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' },
            { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
        ],
    })

    await processEvent(
        '2',
        '127.0.0.1',
        '',
        {
            event: '$autocapture',
            properties,
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    let persons = await hub.db.fetchPersons()
    expect(persons[0].version).toEqual(0)
    expect(persons[0].created_at).toEqual(now)
    let expectedProps = {
        $initial_browser: 'Chrome',
        $initial_browser_version: '95',
        $initial_utm_medium: 'twitter',
        $initial_current_url: 'https://test.com',
        $initial_os: 'Mac OS X',
        utm_medium: 'twitter',
        $initial_gclid: 'GOOGLE ADS ID',
        gclid: 'GOOGLE ADS ID',
    }
    expect(persons[0].properties).toEqual(expectedProps)

    await delayUntilEventIngested(() => hub.db.fetchEvents(), 1)
    await delayUntilEventIngested(() => hub.db.fetchPersons(Database.ClickHouse), 1)
    const chPeople = await hub.db.fetchPersons(Database.ClickHouse)
    expect(chPeople.length).toEqual(1)
    expect(JSON.parse(chPeople[0].properties)).toEqual(expectedProps)
    expect(chPeople[0].created_at).toEqual(now.toFormat('yyyy-MM-dd HH:mm:ss.000'))

    let events = await hub.db.fetchEvents()
    expect(events[0].properties).toEqual({
        $ip: '127.0.0.1',
        $os: 'Mac OS X',
        $set: { utm_medium: 'twitter', gclid: 'GOOGLE ADS ID' },
        token: 'THIS IS NOT A TOKEN FOR TEAM 2',
        $browser: 'Chrome',
        $set_once: {
            $initial_os: 'Mac OS X',
            $initial_browser: 'Chrome',
            $initial_utm_medium: 'twitter',
            $initial_current_url: 'https://test.com',
            $initial_browser_version: '95',
            $initial_gclid: 'GOOGLE ADS ID',
        },
        utm_medium: 'twitter',
        distinct_id: 2,
        $current_url: 'https://test.com',
        $browser_version: '95',
        gclid: 'GOOGLE ADS ID',
        $initial_referrer_url: 'https://google.com/?q=posthog',
        $initial_referring_domain: 'https://google.com',
    })

    // capture a second time to verify e.g. event_names is not ['$autocapture', '$autocapture']
    // Also pass new utm params in to override
    await processEvent(
        '2',
        '127.0.0.1',
        '',
        {
            event: '$autocapture',
            properties: personInitialAndUTMProperties({
                distinct_id: 2,
                token: team.api_token,
                utm_medium: 'instagram',
                $current_url: 'https://test.com/pricing',
                $browser_version: 80,
                $browser: 'Firefox',
                $elements: [
                    { tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' },
                    { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
                ],
            }),
        } as any as PluginEvent,
        team.id,
        DateTime.now(),
        new UUIDT().toString()
    )

    events = await hub.db.fetchEvents()
    persons = await hub.db.fetchPersons()
    expect(events.length).toEqual(2)
    expect(persons.length).toEqual(1)
    expect(persons[0].version).toEqual(1)
    expectedProps = {
        $initial_browser: 'Chrome',
        $initial_browser_version: '95',
        $initial_utm_medium: 'twitter',
        $initial_current_url: 'https://test.com',
        $initial_os: 'Mac OS X',
        utm_medium: 'instagram',
        $initial_gclid: 'GOOGLE ADS ID',
        gclid: 'GOOGLE ADS ID',
    }
    expect(persons[0].properties).toEqual(expectedProps)

    await delayUntilEventIngested(() => hub.db.fetchPersons(Database.ClickHouse), 2)
    const chPeople2 = await hub.db.fetchPersons(Database.ClickHouse)
    expect(chPeople2.length).toEqual(1)
    expect(JSON.parse(chPeople2[0].properties)).toEqual(expectedProps)

    expect(events[1].properties.$set).toEqual({
        utm_medium: 'instagram',
    })
    expect(events[1].properties.$set_once).toEqual({
        $initial_browser: 'Firefox',
        $initial_browser_version: 80,
        $initial_utm_medium: 'instagram',
        $initial_current_url: 'https://test.com/pricing',
    })

    const [person] = persons
    const distinctIds = await hub.db.fetchDistinctIdValues(person)

    const [event] = events as Event[]
    expect(event.distinct_id).toEqual('2')
    expect(distinctIds).toEqual(['2'])
    expect(event.event).toEqual('$autocapture')

    const elements = await hub.db.fetchElements(event)
    expect(elements[0].tag_name).toEqual('a')
    expect(elements[0].attr_class).toEqual(['btn', 'btn-sm'])
    expect(elements[1].order).toEqual(1)
    expect(elements[1].text).toEqual('💻')

    // Don't update any props, set and set_once should be what was sent
    await processEvent(
        '2',
        '127.0.0.1',
        '',
        {
            event: '$autocapture',
            properties: personInitialAndUTMProperties({
                distinct_id: 2,
                token: team.api_token,
                utm_medium: 'instagram',
                $current_url: 'https://test.com/pricing',
                $browser: 'Firefox',

                $elements: [
                    { tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' },
                    { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
                ],
            }),
        } as any as PluginEvent,
        team.id,
        DateTime.now(),
        new UUIDT().toString()
    )

    events = await hub.db.fetchEvents()
    persons = await hub.db.fetchPersons()
    expect(events.length).toEqual(3)
    expect(persons.length).toEqual(1)

    // no new props, person wasn't updated with old fn, was because of timestamps update with new fn
    expect(persons[0].version).toEqual(1)

    expect(events[2].properties.$set).toEqual({
        utm_medium: 'instagram',
    })
    expect(events[2].properties.$set_once).toEqual({
        $initial_browser: 'Firefox',
        $initial_utm_medium: 'instagram',
        $initial_current_url: 'https://test.com/pricing',
    })
    // check that person properties didn't change
    expect(persons[0].properties).toEqual(expectedProps)

    const chPeople3 = await hub.db.fetchPersons(Database.ClickHouse)
    expect(chPeople3.length).toEqual(1)
    expect(JSON.parse(chPeople3[0].properties)).toEqual(expectedProps)

    team = await getFirstTeam(hub)

    expect(await hub.db.fetchEventDefinitions()).toEqual([
        {
            id: expect.any(String),
            name: '$autocapture',
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
            created_at: expect.any(String),
            last_seen_at: expect.any(String),
        },
    ])
    expect(await hub.db.fetchPropertyDefinitions()).toEqual([
        {
            id: expect.any(String),
            is_numerical: true,
            name: 'distinct_id',
            property_type: 'Numeric',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
        {
            id: expect.any(String),
            is_numerical: false,
            name: 'token',
            property_type: 'String',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
        {
            id: expect.any(String),
            is_numerical: false,
            name: '$browser',
            property_type: 'String',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
        {
            id: expect.any(String),
            is_numerical: false,
            name: '$current_url',
            property_type: 'String',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
        {
            id: expect.any(String),
            is_numerical: false,
            name: '$os',
            property_type: 'String',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
        {
            id: expect.any(String),
            is_numerical: true,
            name: '$browser_version',
            property_type: PropertyType.Numeric,
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
        {
            id: expect.any(String),
            is_numerical: false,
            name: '$initial_referring_domain',
            property_type: 'String',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
        {
            id: expect.any(String),
            is_numerical: false,
            name: '$initial_referrer_url',
            property_type: 'String',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
        {
            id: expect.any(String),
            is_numerical: false,
            name: 'utm_medium',
            property_type: 'String',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
        {
            id: expect.any(String),
            is_numerical: false,
            name: 'gclid',
            property_type: 'String',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
        {
            id: expect.any(String),
            is_numerical: false,
            name: '$ip',
            property_type: 'String',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
    ])
})

test('capture bad team', async () => {
    await expect(
        eventsProcessor.processEvent(
            'asdfasdfasdf',
            '',
            {
                event: '$pageview',
                properties: { distinct_id: 'asdfasdfasdf', token: team.api_token },
            } as any as PluginEvent,
            1337,
            now,
            new UUIDT().toString()
        )
    ).rejects.toThrowError("No team found with ID 1337. Can't ingest event.")
})

test('capture no element', async () => {
    await createPerson(hub, team, ['asdfasdfasdf'])

    await processEvent(
        'asdfasdfasdf',
        '',
        '',
        {
            event: '$pageview',
            properties: { distinct_id: 'asdfasdfasdf', token: team.api_token },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect(await hub.db.fetchDistinctIdValues((await hub.db.fetchPersons())[0])).toEqual(['asdfasdfasdf'])
    const [event] = await hub.db.fetchEvents()
    expect(event.event).toBe('$pageview')
})

test('ip none', async () => {
    await createPerson(hub, team, ['asdfasdfasdf'])

    await processEvent(
        'asdfasdfasdf',
        null,
        '',
        {
            event: '$pageview',
            properties: { distinct_id: 'asdfasdfasdf', token: team.api_token },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    const [event] = await hub.db.fetchEvents()
    expect(Object.keys(event.properties)).not.toContain('$ip')
})

test('ip capture', async () => {
    await createPerson(hub, team, ['asdfasdfasdf'])

    await processEvent(
        'asdfasdfasdf',
        '11.12.13.14',
        '',
        {
            event: '$pageview',
            properties: { distinct_id: 'asdfasdfasdf', token: team.api_token },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    const [event] = await hub.db.fetchEvents()
    expect(event.properties['$ip']).toBe('11.12.13.14')
})

test('ip override', async () => {
    await createPerson(hub, team, ['asdfasdfasdf'])

    await processEvent(
        'asdfasdfasdf',
        '11.12.13.14',
        '',
        {
            event: '$pageview',
            properties: { $ip: '1.0.0.1', distinct_id: 'asdfasdfasdf', token: team.api_token },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    const [event] = await hub.db.fetchEvents()
    expect(event.properties['$ip']).toBe('1.0.0.1')
})

test('anonymized ip capture', async () => {
    await hub.db.postgresQuery('update posthog_team set anonymize_ips = $1', [true], 'testTag')
    await createPerson(hub, team, ['asdfasdfasdf'])

    await processEvent(
        'asdfasdfasdf',
        '11.12.13.14',
        '',
        {
            event: '$pageview',
            properties: { distinct_id: 'asdfasdfasdf', token: team.api_token },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    const [event] = await hub.db.fetchEvents()
    expect(event.properties['$ip']).not.toBeDefined()
})

test('alias', async () => {
    await createPerson(hub, team, ['old_distinct_id'])

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$create_alias',
            properties: { distinct_id: 'new_distinct_id', token: team.api_token, alias: 'old_distinct_id' },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues((await hub.db.fetchPersons())[0])).toEqual([
        'old_distinct_id',
        'new_distinct_id',
    ])
})

test('alias reverse', async () => {
    await createPerson(hub, team, ['old_distinct_id'])

    await processEvent(
        'old_distinct_id',
        '',
        '',
        {
            event: '$create_alias',
            properties: { distinct_id: 'old_distinct_id', token: team.api_token, alias: 'new_distinct_id' },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues((await hub.db.fetchPersons())[0])).toEqual([
        'old_distinct_id',
        'new_distinct_id',
    ])
})

test('alias twice', async () => {
    await createPerson(hub, team, ['old_distinct_id'])

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$create_alias',
            properties: { distinct_id: 'new_distinct_id', token: team.api_token, alias: 'old_distinct_id' },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchPersons()).length).toBe(1)
    expect((await hub.db.fetchEvents()).length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues((await hub.db.fetchPersons())[0])).toEqual([
        'old_distinct_id',
        'new_distinct_id',
    ])

    await createPerson(hub, team, ['old_distinct_id_2'])
    expect((await hub.db.fetchPersons()).length).toBe(2)

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$create_alias',
            properties: { distinct_id: 'new_distinct_id', token: team.api_token, alias: 'old_distinct_id_2' },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    expect((await hub.db.fetchEvents()).length).toBe(2)
    expect((await hub.db.fetchPersons()).length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues((await hub.db.fetchPersons())[0])).toEqual([
        'old_distinct_id',
        'new_distinct_id',
        'old_distinct_id_2',
    ])
})

test('alias before person', async () => {
    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$create_alias',
            properties: { distinct_id: 'new_distinct_id', token: team.api_token, alias: 'old_distinct_id' },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)
    expect((await hub.db.fetchPersons()).length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues((await hub.db.fetchPersons())[0])).toEqual([
        'new_distinct_id',
        'old_distinct_id',
    ])
})

test('alias both existing', async () => {
    await createPerson(hub, team, ['old_distinct_id'])
    await createPerson(hub, team, ['new_distinct_id'])

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$create_alias',
            properties: { distinct_id: 'new_distinct_id', token: team.api_token, alias: 'old_distinct_id' },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues((await hub.db.fetchPersons())[0])).toEqual([
        'old_distinct_id',
        'new_distinct_id',
    ])
})

test('alias merge properties', async () => {
    await createPerson(hub, team, ['new_distinct_id'], {
        key_on_both: 'new value both',
        key_on_new: 'new value',
    })
    await createPerson(hub, team, ['old_distinct_id'], {
        key_on_both: 'old value both',
        key_on_old: 'old value',
    })

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$create_alias',
            properties: { distinct_id: 'new_distinct_id', token: team.api_token, alias: 'old_distinct_id' },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)
    expect((await hub.db.fetchPersons()).length).toBe(1)
    const [person] = await hub.db.fetchPersons()
    expect((await hub.db.fetchDistinctIdValues(person)).sort()).toEqual(['new_distinct_id', 'old_distinct_id'])
    expect(person.properties).toEqual({
        key_on_both: 'new value both',
        key_on_new: 'new value',
        key_on_old: 'old value',
    })
})

test('long htext', async () => {
    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$autocapture',
            properties: {
                distinct_id: 'new_distinct_id',
                token: team.api_token,
                $elements: [
                    {
                        tag_name: 'a',
                        $el_text: 'a'.repeat(2050),
                        attr__href: 'a'.repeat(2050),
                        nth_child: 1,
                        nth_of_type: 2,
                        attr__class: 'btn btn-sm',
                    },
                ],
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    const [event] = (await hub.db.fetchEvents()) as Event[]
    const [element] = await hub.db.fetchElements(event)
    expect(element.href?.length).toEqual(2048)
    expect(element.text?.length).toEqual(400)
})

test('capture first team event', async () => {
    await hub.db.postgresQuery(`UPDATE posthog_team SET ingested_event = $1 WHERE id = $2`, [false, team.id], 'testTag')

    posthog.capture = jest.fn() as any
    posthog.identify = jest.fn() as any

    await processEvent(
        '2',
        '',
        '',
        {
            event: '$autocapture',
            properties: {
                distinct_id: 1,
                token: team.api_token,
                $elements: [{ tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' }],
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect(posthog.identify).toHaveBeenCalledWith('plugin_test_user_distinct_id_1001')
    expect(posthog.capture).toHaveBeenCalledWith('first team event ingested', {
        team: team.uuid,
        $groups: {
            project: team.uuid,
            organization: team.organization_id,
            instance: 'unknown',
        },
    })

    team = await getFirstTeam(hub)
    expect(team.ingested_event).toEqual(true)

    const [event] = (await hub.db.fetchEvents()) as Event[]

    const elements = await hub.db.fetchElements(event)
    expect(elements.length).toEqual(1)
})

it('snapshot event not stored if session recording disabled', async () => {
    await hub.db.postgresQuery('update posthog_team set session_recording_opt_in = $1', [false], 'testRecordings')
    await eventsProcessor.processEvent(
        'some-id',
        '',
        {
            event: '$snapshot',
            properties: { $session_id: 'abcf-efg', $snapshot_data: { timestamp: 123 } },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    await delayUntilEventIngested(() => hub.db.fetchSessionRecordingEvents())

    const events = await hub.db.fetchEvents()
    expect(events.length).toEqual(0)

    const sessionRecordingEvents = await hub.db.fetchSessionRecordingEvents()
    expect(sessionRecordingEvents.length).toBe(0)
})

test('snapshot event stored as session_recording_event', async () => {
    await eventsProcessor.processEvent(
        'some-id',
        '',
        {
            event: '$snapshot',
            properties: { $session_id: 'abcf-efg', $snapshot_data: { timestamp: 123 } },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    await delayUntilEventIngested(() => hub.db.fetchSessionRecordingEvents())

    const events = await hub.db.fetchEvents()
    expect(events.length).toEqual(0)

    const sessionRecordingEvents = await hub.db.fetchSessionRecordingEvents()
    expect(sessionRecordingEvents.length).toBe(1)

    const [event] = sessionRecordingEvents
    expect(event.session_id).toEqual('abcf-efg')
    expect(event.distinct_id).toEqual('some-id')
    expect(event.snapshot_data).toEqual({ timestamp: 123 })
})

test('$snapshot event creates new person if needed', async () => {
    await processEvent(
        'some_new_id',
        '',
        '',
        {
            event: '$snapshot',
            properties: { $session_id: 'abcf-efg', $snapshot_data: { timestamp: 123 } },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    await delayUntilEventIngested(() => hub.db.fetchPersons())

    const persons = await hub.db.fetchPersons()

    expect(persons.length).toEqual(1)
})

test('identify set', async () => {
    await createPerson(hub, team, ['distinct_id1'])
    const ts_before = now
    const ts_after = now.plus({ hours: 1 })

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: '$identify',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $set: { a_prop: 'test-1', c_prop: 'test-1' },
            },
        } as any as PluginEvent,
        team.id,
        ts_before,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)

    const [event] = await hub.db.fetchEvents()
    expect(event.properties['$set']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

    const [person] = await hub.db.fetchPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
    expect(person.properties).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })
    expect(person.is_identified).toEqual(false)

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: '$identify',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $set: { a_prop: 'test-2', b_prop: 'test-2b' },
            },
        } as any as PluginEvent,
        team.id,
        ts_after,
        new UUIDT().toString()
    )
    expect((await hub.db.fetchEvents()).length).toBe(2)
    const [person2] = await hub.db.fetchPersons()
    expect(person2.properties).toEqual({ a_prop: 'test-2', b_prop: 'test-2b', c_prop: 'test-1' })
})

test('identify set_once', async () => {
    await createPerson(hub, team, ['distinct_id1'])

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: '$identify',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $set_once: { a_prop: 'test-1', c_prop: 'test-1' },
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)

    const [event] = await hub.db.fetchEvents()
    expect(event.properties['$set_once']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

    const [person] = await hub.db.fetchPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
    expect(person.properties).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })
    expect(person.is_identified).toEqual(false)

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: '$identify',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $set_once: { a_prop: 'test-2', b_prop: 'test-2b' },
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    expect((await hub.db.fetchEvents()).length).toBe(2)
    const [person2] = await hub.db.fetchPersons()
    expect(person2.properties).toEqual({ a_prop: 'test-1', b_prop: 'test-2b', c_prop: 'test-1' })
    expect(person2.is_identified).toEqual(false)
})

test('identify with illegal (generic) id', async () => {
    await createPerson(hub, team, ['im an anonymous id'])
    expect((await hub.db.fetchPersons()).length).toBe(1)

    const createPersonAndSendIdentify = async (distinctId: string): Promise<void> => {
        await createPerson(hub, team, [distinctId])

        await processEvent(
            distinctId,
            '',
            '',
            {
                event: '$identify',
                properties: {
                    token: team.api_token,
                    distinct_id: distinctId,
                    $anon_distinct_id: 'im an anonymous id',
                },
            } as any as PluginEvent,
            team.id,
            now,
            new UUIDT().toString()
        )
    }

    // try to merge, the merge should fail
    await createPersonAndSendIdentify('distinctId')
    expect((await hub.db.fetchPersons()).length).toBe(2)

    await createPersonAndSendIdentify('  ')
    expect((await hub.db.fetchPersons()).length).toBe(3)

    await createPersonAndSendIdentify('NaN')
    expect((await hub.db.fetchPersons()).length).toBe(4)

    await createPersonAndSendIdentify('undefined')
    expect((await hub.db.fetchPersons()).length).toBe(5)

    await createPersonAndSendIdentify('None')
    expect((await hub.db.fetchPersons()).length).toBe(6)

    await createPersonAndSendIdentify('0')
    expect((await hub.db.fetchPersons()).length).toBe(7)

    // 'Nan' is an allowed id, so the merge should work
    // as such, no extra person is created
    await createPersonAndSendIdentify('Nan')
    expect((await hub.db.fetchPersons()).length).toBe(7)
})

test('Alias with illegal (generic) id', async () => {
    const legal_id = 'user123'
    const illegal_id = 'null'
    await createPerson(hub, team, [legal_id])
    expect((await hub.db.fetchPersons()).length).toBe(1)

    await processEvent(
        illegal_id,
        '',
        '',
        {
            event: '$create_alias',
            properties: {
                token: team.api_token,
                distinct_id: legal_id,
                alias: illegal_id,
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    // person with illegal id got created but not merged
    expect((await hub.db.fetchPersons()).length).toBe(2)
})

test('distinct with anonymous_id', async () => {
    await createPerson(hub, team, ['anonymous_id'])

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$identify',
            properties: {
                $anon_distinct_id: 'anonymous_id',
                token: team.api_token,
                distinct_id: 'new_distinct_id',
                $set: { a_prop: 'test' },
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)
    const [event] = await hub.db.fetchEvents()
    expect(event.properties['$set']).toEqual({ a_prop: 'test' })
    const [person] = await hub.db.fetchPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['anonymous_id', 'new_distinct_id'])
    expect(person.properties).toEqual({ a_prop: 'test' })
    expect(person.is_identified).toEqual(true)

    // check no errors as this call can happen multiple times
    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$identify',
            properties: {
                $anon_distinct_id: 'anonymous_id',
                token: team.api_token,
                distinct_id: 'new_distinct_id',
                $set: { a_prop: 'test' },
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
})

// This case is likely to happen after signup, for example:
// 1. User browses website with anonymous_id
// 2. User signs up, triggers event with their new_distinct_id (creating a new Person)
// 3. In the frontend, try to alias anonymous_id with new_distinct_id
// Result should be that we end up with one Person with both ID's
test('distinct with anonymous_id which was already created', async () => {
    await createPerson(hub, team, ['anonymous_id'])
    await createPerson(hub, team, ['new_distinct_id'], { email: 'someone@gmail.com' })

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$identify',
            properties: {
                $anon_distinct_id: 'anonymous_id',
                token: team.api_token,
                distinct_id: 'new_distinct_id',
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    const [person] = await hub.db.fetchPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['anonymous_id', 'new_distinct_id'])
    expect(person.properties['email']).toEqual('someone@gmail.com')
    expect(person.is_identified).toEqual(true)
})

test('identify with the same distinct_id as anon_distinct_id', async () => {
    await createPerson(hub, team, ['anonymous_id'])

    await processEvent(
        'anonymous_id',
        '',
        '',
        {
            event: '$identify',
            properties: {
                $anon_distinct_id: 'anonymous_id',
                token: team.api_token,
                distinct_id: 'anonymous_id',
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    const [person] = await hub.db.fetchPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['anonymous_id'])
    expect(person.is_identified).toEqual(false)
})

test('distinct with multiple anonymous_ids which were already created', async () => {
    await createPerson(hub, team, ['anonymous_id'])
    await createPerson(hub, team, ['new_distinct_id'], { email: 'someone@gmail.com' })

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$identify',
            properties: {
                $anon_distinct_id: 'anonymous_id',
                token: team.api_token,
                distinct_id: 'new_distinct_id',
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    const persons1 = await hub.db.fetchPersons()
    expect(persons1.length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues(persons1[0])).toEqual(['anonymous_id', 'new_distinct_id'])
    expect(persons1[0].properties['email']).toEqual('someone@gmail.com')
    expect(persons1[0].is_identified).toEqual(true)

    await createPerson(hub, team, ['anonymous_id_2'])

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$identify',
            properties: {
                $anon_distinct_id: 'anonymous_id_2',
                token: team.api_token,
                distinct_id: 'new_distinct_id',
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    const persons2 = await hub.db.fetchPersons()
    expect(persons2.length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues(persons2[0])).toEqual([
        'anonymous_id',
        'new_distinct_id',
        'anonymous_id_2',
    ])
    expect(persons2[0].properties['email']).toEqual('someone@gmail.com')
    expect(persons2[0].is_identified).toEqual(true)
})

test('distinct team leakage', async () => {
    await createUserTeamAndOrganization(
        hub.postgres,
        3,
        1002,
        'a73fc995-a63f-4e4e-bf65-2a5e9f93b2b1',
        '01774e2f-0d01-0000-ee94-9a238640c6ee',
        '0174f81e-36f5-0000-7ef8-cc26c1fbab1c'
    )
    const team2 = (await getTeams(hub))[1]
    await createPerson(hub, team2, ['2'], { email: 'team2@gmail.com' })
    await createPerson(hub, team, ['1', '2'])

    await processEvent(
        '2',
        '',
        '',
        {
            event: '$identify',
            properties: {
                $anon_distinct_id: '1',
                token: team.api_token,
                distinct_id: '2',
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    const people = (await hub.db.fetchPersons()).sort((p1, p2) => p2.team_id - p1.team_id)
    expect(people.length).toEqual(2)
    expect(people[1].team_id).toEqual(team.id)
    expect(people[1].properties).toEqual({})
    expect(await hub.db.fetchDistinctIdValues(people[1])).toEqual(['1', '2'])
    expect(people[0].team_id).toEqual(team2.id)
    expect(await hub.db.fetchDistinctIdValues(people[0])).toEqual(['2'])
})

describe('when handling $identify', () => {
    test('we do not alias users if distinct id changes but we are already identified', async () => {
        // This test is in reference to
        // https://github.com/PostHog/posthog/issues/5527 , where we were
        // correctly identifying that an anonymous user before login should be
        // aliased to the user they subsequently login as, but incorrectly
        // aliasing on subsequent $identify events. The anonymous case is
        // special as we want to alias to a known user, but otherwise we
        // shouldn't be doing so.

        const anonymousId = 'anonymous_id'
        const initialDistinctId = 'initial_distinct_id'

        const p2DistinctId = 'p2_distinct_id'
        const p2NewDistinctId = 'new_distinct_id'

        // Play out a sequence of events that should result in two users being
        // identified, with the first to events associated with one user, and
        // the third with another.
        await capture(hub, 'event 1')
        await identify(hub, initialDistinctId)
        await capture(hub, 'event 2')

        state.currentDistinctId = p2DistinctId
        await capture(hub, 'event 3')
        await identify(hub, p2NewDistinctId)
        await capture(hub, 'event 4')

        // Let's also make sure that we do not alias when switching back to
        // initialDistictId
        await identify(hub, initialDistinctId)

        // Get pairins of person distinctIds and the events associated with them
        const eventsByPerson = await getEventsByPerson(hub)

        expect(eventsByPerson).toEqual([
            [
                [anonymousId, initialDistinctId],
                ['event 1', '$identify', 'event 2', '$identify'],
            ],
            [
                [p2DistinctId, p2NewDistinctId],
                ['event 3', '$identify', 'event 4'],
            ],
        ])

        // Make sure the persons are identified
        const persons = await hub.db.fetchPersons()
        expect(persons.map((person) => person.is_identified)).toEqual([true, true])
    })

    test('we do not alias users if distinct id changes but we are already identified, with no anonymous event', async () => {
        // This test is in reference to
        // https://github.com/PostHog/posthog/issues/5527 , where we were
        // correctly identifying that an anonymous user before login should be
        // aliased to the user they subsequently login as, but incorrectly
        // aliasing on subsequent $identify events. The anonymous case is
        // special as we want to alias to a known user, but otherwise we
        // shouldn't be doing so. This test is similar to the previous one,
        // except it does not include an initial anonymous event.

        const anonymousId = 'anonymous_id'
        const initialDistinctId = 'initial_distinct_id'

        const p2DistinctId = 'p2_distinct_id'
        const p2NewDistinctId = 'new_distinct_id'

        // Play out a sequence of events that should result in two users being
        // identified, with the first to events associated with one user, and
        // the third with another.
        await identify(hub, initialDistinctId)
        await capture(hub, 'event 2')

        state.currentDistinctId = p2DistinctId
        await capture(hub, 'event 3')
        await identify(hub, p2NewDistinctId)
        await capture(hub, 'event 4')

        // Let's also make sure that we do not alias when switching back to
        // initialDistictId
        await identify(hub, initialDistinctId)

        // Get pairins of person distinctIds and the events associated with them
        const eventsByPerson = await getEventsByPerson(hub)

        expect(eventsByPerson).toEqual([
            [
                [initialDistinctId, anonymousId],
                ['$identify', 'event 2', '$identify'],
            ],
            [
                [p2DistinctId, p2NewDistinctId],
                ['event 3', '$identify', 'event 4'],
            ],
        ])

        // Make sure the persons are identified
        const persons = await hub.db.fetchPersons()
        expect(persons.map((person) => person.is_identified)).toEqual([true, true])
    })

    test('we do not leave things in inconsistent state if $identify is run concurrently', async () => {
        // There are a few places where we have the pattern of:
        //
        //  1. fetch from postgres
        //  2. check rows match condition
        //  3. perform update
        //
        // This test is designed to check the specific case where, in
        // handling we are creating an unidentified user, then updating this
        // user to have is_identified = true. Since we are using the
        // is_identified to decide on if we will merge persons, we want to
        // make sure we guard against this race condition. The scenario is:
        //
        //  1. initiate identify for 'distinct-id'
        //  2. once person for distinct-id has been created, initiate
        //     identify for 'new-distinct-id'
        //  3. check that the persons remain distinct

        // Check the db is empty to start with
        expect(await hub.db.fetchPersons()).toEqual([])

        const anonymousId = 'anonymous_id'
        const initialDistinctId = 'initial-distinct-id'
        const newDistinctId = 'new-distinct-id'

        state.currentDistinctId = newDistinctId
        await capture(hub, 'some event')
        state.currentDistinctId = anonymousId

        // Hook into createPerson, which is as of writing called from
        // alias. Here we simply call identify again and wait on it
        // completing before continuing with the first identify.
        const originalCreatePerson = hub.db.createPerson.bind(hub.db)
        const createPersonMock = jest.fn(async (...args) => {
            const result = await originalCreatePerson(...args)

            if (createPersonMock.mock.calls.length === 1) {
                // On second invocation, make another identify call
                await identify(hub, newDistinctId)
            }

            return result
        })
        hub.db.createPerson = createPersonMock

        // set the first identify going
        await identify(hub, initialDistinctId)

        // Let's first just make sure `updatePerson` was called, as a way of
        // checking that our mocking was actually invoked
        expect(hub.db.createPerson).toHaveBeenCalled()

        // Now make sure that we have one person in the db that has been
        // identified
        const persons = await hub.db.fetchPersons()
        expect(persons.length).toEqual(2)
        expect(persons.map((person) => person.is_identified)).toEqual([true, true])
    })
})

describe('when handling $create_alias', () => {
    test('we can alias an identified person to an identified person', async () => {
        const anonymousId = 'anonymous_id'
        const identifiedId1 = 'identified_id1'
        const identifiedId2 = 'identified_id2'

        // anonymous_id -> identified_id1
        await identify(hub, identifiedId1)

        state.currentDistinctId = identifiedId1
        await capture(hub, 'some event')

        await identify(hub, identifiedId2)

        await alias(hub, identifiedId1, identifiedId2)

        // Get pairings of person distinctIds and the events associated with them
        const eventsByPerson = await getEventsByPerson(hub)

        // There should just be one person, to which all events are associated
        expect(eventsByPerson).toEqual([
            [
                expect.arrayContaining([anonymousId, identifiedId1, identifiedId2]),
                ['$identify', 'some event', '$identify', '$create_alias'],
            ],
        ])

        // Make sure there is one identified person
        const persons = await hub.db.fetchPersons()
        expect(persons.map((person) => person.is_identified)).toEqual([true])
    })

    test('we can alias an anonymous person to an identified person', async () => {
        const anonymousId = 'anonymous_id'
        const initialDistinctId = 'initial_distinct_id'

        // Identify one person, then become anonymous
        await identify(hub, initialDistinctId)
        state.currentDistinctId = anonymousId
        await capture(hub, 'anonymous event')

        // Then try to alias them
        await alias(hub, anonymousId, initialDistinctId)

        // Get pairings of person distinctIds and the events associated with them
        const eventsByPerson = await getEventsByPerson(hub)

        // There should just be one person, to which all events are associated
        expect(eventsByPerson).toEqual([
            [
                [initialDistinctId, anonymousId],
                ['$identify', 'anonymous event', '$create_alias'],
            ],
        ])

        // Make sure there is one identified person
        const persons = await hub.db.fetchPersons()
        expect(persons.map((person) => person.is_identified)).toEqual([true])
    })

    test('we can alias an identified person to an anonymous person', async () => {
        const anonymousId = 'anonymous_id'
        const initialDistinctId = 'initial_distinct_id'

        // Identify one person, then become anonymous
        await identify(hub, initialDistinctId)
        state.currentDistinctId = anonymousId
        await capture(hub, 'anonymous event')

        // Then try to alias them
        await alias(hub, initialDistinctId, anonymousId)

        // Get pairings of person distinctIds and the events associated with them
        const eventsByPerson = await getEventsByPerson(hub)

        // There should just be one person, to which all events are associated
        expect(eventsByPerson).toEqual([
            [
                [initialDistinctId, anonymousId],
                ['$identify', 'anonymous event', '$create_alias'],
            ],
        ])

        // Make sure there is one identified person
        const persons = await hub.db.fetchPersons()
        expect(persons.map((person) => person.is_identified)).toEqual([true])
    })

    test('we can alias an anonymous person to an anonymous person', async () => {
        const anonymous1 = 'anonymous-1'
        const anonymous2 = 'anonymous-2'

        // Identify one person, then become anonymous
        state.currentDistinctId = anonymous1
        await capture(hub, 'anonymous event 1')
        state.currentDistinctId = anonymous2
        await capture(hub, 'anonymous event 2')

        // Then try to alias them
        await alias(hub, anonymous1, anonymous2)

        // Get pairings of person distinctIds and the events associated with them
        const eventsByPerson = await getEventsByPerson(hub)

        // There should just be one person, to which all events are associated
        expect(eventsByPerson).toEqual([
            [
                [anonymous1, anonymous2],
                ['anonymous event 1', 'anonymous event 2', '$create_alias'],
            ],
        ])

        // Make sure there is one identified person
        const persons = await hub.db.fetchPersons()
        expect(persons.map((person) => person.is_identified)).toEqual([false])
    })

    test('we can alias two non-existent persons', async () => {
        const anonymous1 = 'anonymous-1'
        const anonymous2 = 'anonymous-2'

        // Then try to alias them
        state.currentDistinctId = anonymous1
        await alias(hub, anonymous2, anonymous1)

        // Get pairings of person distinctIds and the events associated with them
        const eventsByPerson = await getEventsByPerson(hub)

        // There should just be one person, to which all events are associated
        expect(eventsByPerson).toEqual([[[anonymous1, anonymous2], ['$create_alias']]])

        // Make sure there is one non-identified person
        const persons = await hub.db.fetchPersons()
        expect(persons.map((person) => person.is_identified)).toEqual([false])
    })
})

test('team event_properties', async () => {
    expect(await hub.db.fetchEventDefinitions()).toEqual([])
    expect(await hub.db.fetchEventProperties()).toEqual([])
    expect(await hub.db.fetchPropertyDefinitions()).toEqual([])

    await processEvent(
        'xxx',
        '127.0.0.1',
        '',
        { event: 'purchase', properties: { price: 299.99, name: 'AirPods Pro' } } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    team = await getFirstTeam(hub)

    expect(await hub.db.fetchEventDefinitions()).toEqual([
        {
            id: expect.any(String),
            name: 'purchase',
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
            created_at: expect.any(String),
            last_seen_at: expect.any(String),
        },
    ])
    expect(await hub.db.fetchPropertyDefinitions()).toEqual([
        {
            id: expect.any(String),
            is_numerical: true,
            name: 'price',
            property_type: 'Numeric',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
        {
            id: expect.any(String),
            is_numerical: false,
            name: 'name',
            property_type: 'String',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
        {
            id: expect.any(String),
            is_numerical: false,
            name: '$ip',
            property_type: 'String',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: 2,
            volume_30_day: null,
        },
    ])

    // flushed every minute normally, triggering flush now, it's tested elsewhere
    expect(await hub.db.fetchEventProperties()).toEqual([
        {
            id: expect.any(Number),
            event: 'purchase',
            property: 'price',
            team_id: 2,
        },
        {
            id: expect.any(Number),
            event: 'purchase',
            property: 'name',
            team_id: 2,
        },
        {
            id: expect.any(Number),
            event: 'purchase',
            property: '$ip',
            team_id: 2,
        },
    ])
})

test('event name object json', async () => {
    await processEvent(
        'xxx',
        '',
        '',
        { event: { 'event name': 'as object' }, properties: {} } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    const [event] = await hub.db.fetchEvents()
    expect(event.event).toEqual('{"event name":"as object"}')
})

test('event name array json', async () => {
    await processEvent(
        'xxx',
        '',
        '',
        { event: ['event name', 'a list'], properties: {} } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    const [event] = await hub.db.fetchEvents()
    expect(event.event).toEqual('["event name","a list"]')
})

test('long event name substr', async () => {
    await processEvent(
        'xxx',
        '',
        '',
        { event: 'E'.repeat(300), properties: { price: 299.99, name: 'AirPods Pro' } } as any as PluginEvent,
        team.id,
        DateTime.utc(),
        new UUIDT().toString()
    )

    const [event] = await hub.db.fetchEvents()
    expect(event.event?.length).toBe(200)
})

test('throws with bad uuid', async () => {
    await expect(
        eventsProcessor.processEvent(
            'xxx',
            '',
            { event: 'E', properties: { price: 299.99, name: 'AirPods Pro' } } as any as PluginEvent,
            team.id,
            DateTime.utc(),
            'this is not an uuid'
        )
    ).rejects.toEqual(new Error('Not a valid UUID: "this is not an uuid"'))

    await expect(
        eventsProcessor.processEvent(
            'xxx',
            '',
            { event: 'E', properties: { price: 299.99, name: 'AirPods Pro' } } as any as PluginEvent,
            team.id,
            DateTime.utc(),
            null as any
        )
    ).rejects.toEqual(new Error('Not a valid UUID: "null"'))
})

test('any event can do $set on props (user exists)', async () => {
    await createPerson(hub, team, ['distinct_id1'])

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_event',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $set: { a_prop: 'test-1', c_prop: 'test-1' },
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)

    const [event] = await hub.db.fetchEvents()
    expect(event.properties['$set']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

    const [person] = await hub.db.fetchPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
    expect(person.properties).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })
})

test('any event can do $set on props (new user)', async () => {
    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_event',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $set: { a_prop: 'test-1', c_prop: 'test-1' },
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)

    const [event] = await hub.db.fetchEvents()
    expect(event.properties['$set']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

    const [person] = await hub.db.fetchPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
    expect(person.properties).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })
})

test('any event can do $set_once on props', async () => {
    await createPerson(hub, team, ['distinct_id1'])

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_event',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $set_once: { a_prop: 'test-1', c_prop: 'test-1' },
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)

    const [event] = await hub.db.fetchEvents()
    expect(event.properties['$set_once']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

    const [person] = await hub.db.fetchPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
    expect(person.properties).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_other_event',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $set_once: { a_prop: 'test-2', b_prop: 'test-2b' },
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    expect((await hub.db.fetchEvents()).length).toBe(2)
    const [person2] = await hub.db.fetchPersons()
    expect(person2.properties).toEqual({ a_prop: 'test-1', b_prop: 'test-2b', c_prop: 'test-1' })
})

test('$set and $set_once', async () => {
    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_event',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $set: { key1: 'value1', key2: 'value2', key3: 'value4' },
                $set_once: { key1_once: 'value1', key2_once: 'value2', key3_once: 'value4' },
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)

    const [person] = await hub.db.fetchPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
    expect(person.properties).toEqual({
        key1: 'value1',
        key2: 'value2',
        key3: 'value4',
        key1_once: 'value1',
        key2_once: 'value2',
        key3_once: 'value4',
    })
})

test('groupidentify', async () => {
    await createPerson(hub, team, ['distinct_id1'])

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: '$groupidentify',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $group_type: 'organization',
                $group_key: 'org::5',
                $group_set: {
                    foo: 'bar',
                },
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)
    await delayUntilEventIngested(() => hub.db.fetchClickhouseGroups(), 1)

    const [clickhouseGroup] = await hub.db.fetchClickhouseGroups()
    expect(clickhouseGroup).toEqual({
        group_key: 'org::5',
        group_properties: JSON.stringify({ foo: 'bar' }),
        group_type_index: 0,
        team_id: team.id,
        created_at: expect.any(String),
    })

    const group = await hub.db.fetchGroup(team.id, 0, 'org::5')
    expect(group).toEqual({
        id: expect.any(Number),
        team_id: team.id,
        group_type_index: 0,
        group_key: 'org::5',
        group_properties: { foo: 'bar' },
        created_at: now,
        properties_last_updated_at: { foo: now.toISO() },
        properties_last_operation: { foo: PropertyUpdateOperation.Set },
        version: 1,
    })
})

test('$groupidentify updating properties', async () => {
    const next: DateTime = now.plus({ minutes: 1 })

    await createPerson(hub, team, ['distinct_id1'])
    await hub.db.insertGroup(
        team.id,
        0,
        'org::5',
        { a: 1, b: 2 },
        now,
        { a: now.toISO(), b: now.toISO() },
        { a: PropertyUpdateOperation.Set, b: PropertyUpdateOperation.Set },
        1
    )

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: '$groupidentify',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $group_type: 'organization',
                $group_key: 'org::5',
                $group_set: {
                    foo: 'bar',
                    a: 3,
                },
            },
        } as any as PluginEvent,
        team.id,
        next,
        new UUIDT().toString()
    )

    expect((await hub.db.fetchEvents()).length).toBe(1)
    await delayUntilEventIngested(() => hub.db.fetchClickhouseGroups(), 1)

    const [clickhouseGroup] = await hub.db.fetchClickhouseGroups()
    expect(clickhouseGroup).toEqual({
        group_key: 'org::5',
        group_properties: JSON.stringify({ a: 3, b: 2, foo: 'bar' }),
        group_type_index: 0,
        team_id: team.id,
        created_at: expect.any(String),
    })

    const group = await hub.db.fetchGroup(team.id, 0, 'org::5')
    expect(group).toEqual({
        id: expect.any(Number),
        team_id: team.id,
        group_type_index: 0,
        group_key: 'org::5',
        group_properties: { a: 3, b: 2, foo: 'bar' },
        created_at: now,
        properties_last_updated_at: { a: next.toISO(), b: now.toISO(), foo: next.toISO() },
        properties_last_operation: {
            a: PropertyUpdateOperation.Set,
            b: PropertyUpdateOperation.Set,
            foo: PropertyUpdateOperation.Set,
        },
        version: 2,
    })
})

test('person and group properties on events', async () => {
    // setup 2 groups with properties
    hub.db.personAndGroupsCachingEnabledTeams.add(2)
    await createPerson(hub, team, ['distinct_id1'], { pineapple: 'on', pizza: 1 })

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: '$groupidentify',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $group_type: 'organization',
                $group_key: 'org:5',
                $group_set: {
                    foo: 'bar',
                },
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: '$groupidentify',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $group_type: 'second',
                $group_key: 'second_key',
                $group_set: {
                    pineapple: 'yummy',
                },
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'test event',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $set: { new: 5 },
                $group_0: 'org:5',
                $group_1: 'second_key',
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )

    const events = await hub.db.fetchEvents()
    const event = [...events].find((e: any) => e['event'] === 'test event')
    expect(event?.person_properties).toEqual({ pineapple: 'on', pizza: 1, new: 5 })
    expect(event?.group0_properties).toEqual({ foo: 'bar' })
    expect(event?.group1_properties).toEqual({ pineapple: 'yummy' })

    hub.db.personAndGroupsCachingEnabledTeams.delete(2)
})

test('set and set_once on the same key', async () => {
    await createPerson(hub, team, ['distinct_id1'])

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_event',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $set: { a_prop: 'test-set' },
                $set_once: { a_prop: 'test-set_once' },
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    expect((await hub.db.fetchEvents()).length).toBe(1)

    const [event] = await hub.db.fetchEvents()
    expect(event.properties['$set']).toEqual({ a_prop: 'test-set' })
    expect(event.properties['$set_once']).toEqual({ a_prop: 'test-set_once' })

    const [person] = await hub.db.fetchPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
    expect(person.properties).toEqual({ a_prop: 'test-set' })
})

test('$unset person property', async () => {
    await createPerson(hub, team, ['distinct_id1'], { a: 1, b: 2, c: 3 })

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_event',
            properties: {
                token: team.api_token,
                distinct_id: 'distinct_id1',
                $unset: ['a', 'c'],
            },
        } as any as PluginEvent,
        team.id,
        now,
        new UUIDT().toString()
    )
    expect((await hub.db.fetchEvents()).length).toBe(1)

    const [event] = await hub.db.fetchEvents()
    expect(event.properties['$unset']).toEqual(['a', 'c'])

    const [person] = await hub.db.fetchPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
    expect(person.properties).toEqual({ b: 2 })
})

describe('ingestion in any order', () => {
    const ts0: DateTime = now
    const ts1: DateTime = now.plus({ minutes: 1 })
    const ts2: DateTime = now.plus({ minutes: 2 })
    const ts3: DateTime = now.plus({ minutes: 3 })
    // key encodes when the value is updated, e.g. s0 means only set call for the 0th event
    // s03o23 means via a set in events number 0 and 3 plus via set_once on 2nd and 3rd event
    // the value corresponds to which call updated it + random letter (same letter for the same key)
    // the letter is for verifying we update the right key only
    const set0: Properties = { s0123o0123: 's0a', s02o13: 's0b', s013: 's0e' }
    const setOnce0: Properties = { s0123o0123: 'o0a', s13o02: 'o0g', o023: 'o0f' }
    const set1: Properties = { s0123o0123: 's1a', s13o02: 's1g', s1: 's1c', s013: 's1e' }
    const setOnce1: Properties = { s0123o0123: 'o1a', s02o13: 'o1b', o1: 'o1d' }
    const set2: Properties = { s0123o0123: 's2a', s02o13: 's2b' }
    const setOnce2: Properties = { s0123o0123: 'o2a', s13o02: 'o2g', o023: 'o2f' }
    const set3: Properties = { s0123o0123: 's3a', s13o02: 's3g', s013: 's3e' }
    const setOnce3: Properties = { s0123o0123: 'o3a', s02o13: 'o3b', o023: 'o3f' }

    beforeEach(async () => {
        await createPerson(hub, team, ['distinct_id1'])
    })

    async function verifyPersonPropertiesSetCorrectly() {
        expect((await hub.db.fetchEvents()).length).toBe(4)

        const [person] = await hub.db.fetchPersons()
        expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
        expect(person.properties).toEqual({
            s0123o0123: 's3a',
            s02o13: 's2b',
            s1: 's1c',
            o1: 'o1d',
            s013: 's3e',
            o023: 'o0f',
            s13o02: 's3g',
        })
        expect(person.version).toEqual(4)
    }

    async function runProcessEvent(set: Properties, setOnce: Properties, ts: DateTime) {
        await processEvent(
            'distinct_id1',
            '',
            '',
            {
                event: 'some_event',
                properties: {
                    $set: set,
                    $set_once: setOnce,
                },
            } as any as PluginEvent,
            team.id,
            ts,
            new UUIDT().toString()
        )
    }

    async function ingest0() {
        await runProcessEvent(set0, setOnce0, ts0)
    }
    async function ingest1() {
        await runProcessEvent(set1, setOnce1, ts1)
    }
    async function ingest2() {
        await runProcessEvent(set2, setOnce2, ts2)
    }
    async function ingest3() {
        await runProcessEvent(set3, setOnce3, ts3)
    }

    test('ingestion in order', async () => {
        await ingest0()
        await ingest1()
        await ingest2()
        await ingest3()
        await verifyPersonPropertiesSetCorrectly()
    })
})
