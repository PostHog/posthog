/*
This file contains a bunch of legacy E2E tests mixed with unit tests.

Rather than add tests here, consider improving event-pipeline-integration test suite or adding
unit tests to appropriate classes/functions.
*/

import { Properties } from '@posthog/plugin-scaffold'
import { PluginEvent } from '@posthog/plugin-scaffold/src/types'
import assert from 'assert'
import * as IORedis from 'ioredis'
import { DateTime } from 'luxon'

import {
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_GROUPS,
    KAFKA_PERSON,
} from '../../src/config/kafka-topics'
import {
    ClickHouseEvent,
    ClickHousePerson,
    Database,
    Hub,
    LogLevel,
    Person,
    PluginsServerConfig,
    PropertyDefinitionTypeEnum,
} from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { KafkaProducerWrapper } from '../../src/utils/db/kafka-producer-wrapper'
import { personInitialAndUTMProperties } from '../../src/utils/db/utils'
import { parseRawClickHouseEvent } from '../../src/utils/event'
import { posthog } from '../../src/utils/posthog'
import { UUIDT } from '../../src/utils/utils'
import { EventPipelineRunner } from '../../src/worker/ingestion/event-pipeline/runner'
import {
    createPerformanceEvent,
    createSessionRecordingEvent,
    EventsProcessor,
} from '../../src/worker/ingestion/process-event'
import { fetchTeam } from '../../src/worker/ingestion/team-manager'
import { createOrganization, createTeam, createUserTeamAndOrganization, resetTestDatabase } from '../helpers/sql'

jest.mock('../../src/utils/status')
jest.setTimeout(600000) // 600 sec timeout.

export async function createPerson(
    server: Hub,
    teamId: number,
    distinctIds: string[],
    properties: Record<string, any> = {}
): Promise<Person> {
    return server.db.createPerson(
        DateTime.utc(),
        properties,
        {},
        {},
        teamId,
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
    const persons = await fetchPostgresPersons()
    const events = fetchEvents()

    return await Promise.all(
        persons.map(async (person) => {
            const distinctIds = await hub.db.fetchDistinctIdValues(person)

            return [
                distinctIds,
                (events as ClickHouseEvent[])
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

let teamId: number
let apiToken: string
let organizationId: string
let teamUuid: string
let hub: Hub
let closeHub: () => Promise<void>
let redis: IORedis.Redis
let eventsProcessor: EventsProcessor
let now = DateTime.utc()

// Store produced rows in memory for inspection mapped from team_id, to topic
// name to rows.
let clickHouseRows: Record<number, Record<string, any[]>> = {}

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
}

// Simple client used to simulate sending events
// Use state object to simulate stateful clients that keep track of old
// distinct id, starting with an anonymous one. I've taken posthog-js as
// the reference implementation.
let state = { currentDistinctId: 'anonymous_id' }

beforeEach(async () => {
    ;[hub, closeHub] = await createTestHub()
    const testCode = `
            function processEvent (event, meta) {
                event.properties["somewhere"] = "over the rainbow";
                return event
            }
        `
    ;({ teamId, apiToken, organizationId, teamUuid } = await resetTestDatabase(testCode, {
        withExtendedTestData: false,
    }))
    eventsProcessor = new EventsProcessor(hub)
    now = DateTime.utc()

    // clear the webhook redis cache
    const hooksCacheKey = `@posthog/plugin-server/hooks/${teamId}`
    await redis.del(hooksCacheKey)

    // Always start with an anonymous state
    state = { currentDistinctId: 'anonymous_id' }

    // Typically we would ingest into ClickHouse. Instead we can just mock and
    // record the produced messages. For all messages we append to the
    // approriate place in the clickHouseRows object. Note that while this is
    // called `queueMessage` singular, it actually contains multiple messages as
    // `record.messages` is an array. Use the team_id in the message's value to
    // determine which team it belongs to.
    clickHouseRows = {}
    jest.spyOn(hub.kafkaProducer, 'queueMessage').mockImplementation(async (record) => {
        for (const message of record.messages) {
            const value = message.value ? JSON.parse(message.value.toString()) : null
            const teamId = value.team_id
            const topic = record.topic
            if (!clickHouseRows[teamId]) {
                clickHouseRows[teamId] = {}
            }
            if (!clickHouseRows[teamId][topic]) {
                clickHouseRows[teamId][topic] = []
            }
            clickHouseRows[teamId][topic].push(value)
        }
        return Promise.resolve()
    })
})

afterAll(async () => {
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
        team_id: teamId,
        uuid: new UUIDT().toString(),
    }
    const runner = new EventPipelineRunner(hub, event)
    await runner.runEventPipeline(event)
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

const fetchEvents = (specificTeamId: number = teamId): ClickHouseEvent[] => {
    // Pull out the events from the clickHouseRows object defaulting to using
    // the global teamId if not specified
    const events = clickHouseRows[specificTeamId][KAFKA_EVENTS_JSON] ?? []
    return events.map(parseRawClickHouseEvent)
}

const fetchClickHousePersons = (specificTeamId: number = teamId): ClickHousePerson[] => {
    // Pull out the persons from the clickHouseRows object defaulting to using
    // the global teamId if not specified. Note the ClickHouse persons table is
    // a ReplacingMergeTree table using the person id for the key, which means
    // we just want to get the latest version of each person. Version is
    // specified by the `version` attribute of the rows and is a monotonically
    // increasing number per person id.
    //
    // Further, if the is_deleted attribute is true for the latest version, we
    // do not want to include that person in the results.
    const persons = clickHouseRows[specificTeamId][KAFKA_PERSON] ?? []
    const latestPersons: Record<string, ClickHousePerson> = {}
    for (const person of persons) {
        const personId = person.id
        if (!latestPersons[personId] || latestPersons[personId].version < person.version) {
            latestPersons[personId] = person
        }
    }
    return Object.values(latestPersons).filter((p) => !p.is_deleted)
}

const fetchPostgresPersons = async (specificTeamId: number = teamId): Promise<Person[]> => {
    return (await hub.db.fetchPersons(Database.Postgres)).filter((p) => p.team_id === specificTeamId)
}

const fetchEventDefinitions = async (specificTeamId: number = teamId): Promise<any[]> => {
    return (await hub.db.fetchEventDefinitions()).filter((p) => p.team_id === specificTeamId)
}

const fetchEventProperties = async (specificTeamId: number = teamId): Promise<any[]> => {
    return (await hub.db.fetchEventProperties()).filter((p) => p.team_id === specificTeamId)
}

const fetchPropertyDefinitions = async (specificTeamId: number = teamId): Promise<any[]> => {
    return (await hub.db.fetchPropertyDefinitions()).filter((p) => p.team_id === specificTeamId)
}

const fetchClickhouseGroups = (specificTeamId: number = teamId): any[] => {
    // Pull out the groups from the clickHouseRows object
    const groups = clickHouseRows[specificTeamId][KAFKA_GROUPS] ?? []
    return groups.map((group) => ({
        ...group,
        properties: group.properties ? JSON.parse(group.properties) : undefined,
        team_id: teamId,
        version: undefined,
    }))
}

const deleteTeam = async (teamId: number): Promise<void> => {
    await hub.postgres.query('DELETE FROM posthog_team WHERE id = $1', [teamId])
}

test('merge people', async () => {
    const p0 = await createPerson(hub, teamId, ['person_0'], { $os: 'Microsoft' })

    await hub.db.updatePersonDeprecated(p0, { created_at: DateTime.fromISO('2020-01-01T00:00:00Z') })

    const p1 = await createPerson(hub, teamId, ['person_1'], { $os: 'Chrome', $browser: 'Chrome' })
    await hub.db.updatePersonDeprecated(p1, { created_at: DateTime.fromISO('2019-07-01T00:00:00Z') })

    await processEvent(
        'person_1',
        '',
        '',
        {
            event: 'user signed up',
            properties: {},
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect((await fetchPostgresPersons()).length).toEqual(2)

    const chPeople = fetchClickHousePersons()
    expect(chPeople.length).toEqual(2)

    await processEvent(
        'person_0',
        '',
        '',
        {
            event: '$identify',
            properties: { $anon_distinct_id: 'person_1' },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(fetchClickHousePersons().length).toEqual(1)

    const [person] = await fetchPostgresPersons()

    expect(person.properties).toEqual({ $os: 'Microsoft', $browser: 'Chrome' })
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['person_0', 'person_1'])
    expect(person.created_at.toISO()).toEqual(DateTime.fromISO('2019-07-01T00:00:00Z').setZone('UTC').toISO())
})

test('capture new person', async () => {
    await hub.db.postgresQuery(
        `UPDATE posthog_team
             SET ingested_event = $1
             WHERE id = $2`,
        [true, teamId],
        'testTag'
    )

    expect(await fetchEventDefinitions()).toEqual([])
    expect(await fetchPropertyDefinitions()).toEqual([])

    const properties = personInitialAndUTMProperties({
        distinct_id: 2,
        token: apiToken,
        $browser: 'Chrome',
        $current_url: 'https://test.com',
        $os: 'Mac OS X',
        $browser_version: '95',
        $referring_domain: 'https://google.com',
        $referrer: 'https://google.com/?q=posthog',
        utm_medium: 'twitter',
        gclid: 'GOOGLE ADS ID',
        msclkid: 'BING ADS ID',
        $elements: [
            { tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' },
            { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
        ],
    })

    const uuid = new UUIDT().toString()
    await processEvent(
        '2',
        '127.0.0.1',
        '',
        {
            event: '$autocapture',
            properties,
        } as any as PluginEvent,
        teamId,
        now,
        uuid
    )

    let persons = await fetchPostgresPersons()
    expect(persons[0].version).toEqual(0)
    expect(persons[0].created_at).toEqual(now)
    let expectedProps = {
        $creator_event_uuid: uuid,
        $initial_browser: 'Chrome',
        $initial_browser_version: '95',
        $initial_utm_medium: 'twitter',
        $initial_current_url: 'https://test.com',
        $initial_os: 'Mac OS X',
        utm_medium: 'twitter',
        $initial_gclid: 'GOOGLE ADS ID',
        $initial_msclkid: 'BING ADS ID',
        gclid: 'GOOGLE ADS ID',
        msclkid: 'BING ADS ID',
        $initial_referrer: 'https://google.com/?q=posthog',
        $initial_referring_domain: 'https://google.com',
    }
    expect(persons[0].properties).toEqual(expectedProps)

    const chPeople = fetchClickHousePersons()
    expect(chPeople.length).toEqual(1)
    expect(JSON.parse(chPeople[0].properties)).toEqual(expectedProps)
    // Compare the chPeople[0].created_at which is string in the iso8601 date
    // format _without_ the "T" between dates and times parts (as ClickHouse
    // complains if we include the "T"), to the now variable. They should be
    // equivalent excluding the milliseconds parts.
    expect(chPeople[0].created_at).toEqual(now.toISO().replace('T', ' ').slice(0, -5))

    let events = fetchEvents()
    expect(events[0].properties).toEqual({
        $ip: '127.0.0.1',
        $os: 'Mac OS X',
        $set: { utm_medium: 'twitter', gclid: 'GOOGLE ADS ID', msclkid: 'BING ADS ID' },
        token: expect.any(String),
        $browser: 'Chrome',
        $set_once: {
            $initial_os: 'Mac OS X',
            $initial_browser: 'Chrome',
            $initial_utm_medium: 'twitter',
            $initial_current_url: 'https://test.com',
            $initial_browser_version: '95',
            $initial_gclid: 'GOOGLE ADS ID',
            $initial_msclkid: 'BING ADS ID',
            $initial_referrer: 'https://google.com/?q=posthog',
            $initial_referring_domain: 'https://google.com',
        },
        utm_medium: 'twitter',
        distinct_id: 2,
        $current_url: 'https://test.com',
        $browser_version: '95',
        gclid: 'GOOGLE ADS ID',
        msclkid: 'BING ADS ID',
        $referrer: 'https://google.com/?q=posthog',
        $referring_domain: 'https://google.com',
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
                token: apiToken,
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
        teamId,
        DateTime.now(),
        new UUIDT().toString()
    )

    events = fetchEvents()
    persons = await fetchPostgresPersons()
    expect(events.length).toEqual(2)
    expect(persons.length).toEqual(1)
    expect(persons[0].version).toEqual(1)
    expectedProps = {
        $creator_event_uuid: uuid,
        $initial_browser: 'Chrome',
        $initial_browser_version: '95',
        $initial_utm_medium: 'twitter',
        $initial_current_url: 'https://test.com',
        $initial_os: 'Mac OS X',
        utm_medium: 'instagram',
        $initial_gclid: 'GOOGLE ADS ID',
        $initial_msclkid: 'BING ADS ID',
        gclid: 'GOOGLE ADS ID',
        msclkid: 'BING ADS ID',
        $initial_referrer: 'https://google.com/?q=posthog',
        $initial_referring_domain: 'https://google.com',
    }
    expect(persons[0].properties).toEqual(expectedProps)

    const chPeople2 = fetchClickHousePersons().filter((p) => p && JSON.parse(p.properties).utm_medium == 'instagram')
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

    const [event] = events as ClickHouseEvent[]
    expect(event.distinct_id).toEqual('2')
    expect(distinctIds).toEqual(['2'])
    expect(event.event).toEqual('$autocapture')

    const elements = event.elements_chain!
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
                token: apiToken,
                utm_medium: 'instagram',
                $current_url: 'https://test.com/pricing',
                $browser: 'Firefox',

                $elements: [
                    { tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' },
                    { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
                ],
            }),
        } as any as PluginEvent,
        teamId,
        DateTime.now(),
        new UUIDT().toString()
    )

    events = fetchEvents()
    persons = await fetchPostgresPersons()
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

    const chPeople3 = fetchClickHousePersons()
    expect(chPeople3.length).toEqual(1)
    expect(JSON.parse(chPeople3[0].properties)).toEqual(expectedProps)

    expect(await fetchEventDefinitions()).toEqual([
        {
            id: expect.any(String),
            name: '$autocapture',
            query_usage_30_day: null,
            team_id: teamId,
            volume_30_day: null,
            created_at: expect.any(String),
            last_seen_at: expect.any(String),
        },
    ])
    expect(await fetchPropertyDefinitions()).toEqual(
        expect.arrayContaining([
            {
                id: expect.any(String),
                is_numerical: true,
                name: 'distinct_id',
                property_type: 'Numeric',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 1,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: 'token',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 1,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$browser',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 1,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$current_url',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 1,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$os',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 1,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: true,
                name: '$browser_version',
                property_type: 'Numeric',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 1,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$referring_domain',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 1,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$referrer',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 1,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: 'utm_medium',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 1,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: 'gclid',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 1,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: 'msclkid',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 1,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$ip',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 1,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: 'utm_medium',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 2,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: 'gclid',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 2,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: 'msclkid',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 2,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$initial_browser',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 2,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$initial_current_url',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 2,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$initial_os',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 2,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: true,
                name: '$initial_browser_version',
                property_type: 'Numeric',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 2,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$initial_referring_domain',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 2,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$initial_referrer',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 2,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$initial_utm_medium',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 2,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$initial_gclid',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 2,
                group_type_index: null,
                volume_30_day: null,
            },
            {
                id: expect.any(String),
                is_numerical: false,
                name: '$initial_msclkid',
                property_type: 'String',
                property_type_format: null,
                query_usage_30_day: null,
                team_id: teamId,
                type: 2,
                group_type_index: null,
                volume_30_day: null,
            },
        ])
    )
})

test('capture bad team', async () => {
    // Create and delete a team to get a team ID that doesn't exist
    const otherOrganizationId = await createOrganization()
    const otherTeamId = await createTeam(otherOrganizationId)
    await deleteTeam(otherTeamId)
    await expect(
        eventsProcessor.processEvent(
            'asdfasdfasdf',
            '',
            {
                event: '$pageview',
                properties: { distinct_id: 'asdfasdfasdf', token: apiToken },
            } as any as PluginEvent,
            otherTeamId,
            now,
            new UUIDT().toString()
        )
    ).rejects.toThrowError(`No team found with ID ${otherTeamId}. Can't ingest event.`)
})

test('capture no element', async () => {
    await createPerson(hub, teamId, ['asdfasdfasdf'])

    await processEvent(
        'asdfasdfasdf',
        '',
        '',
        {
            event: '$pageview',
            properties: { distinct_id: 'asdfasdfasdf', token: apiToken },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(await hub.db.fetchDistinctIdValues((await fetchPostgresPersons())[0])).toEqual(['asdfasdfasdf'])
    const [event] = fetchEvents()
    expect(event.event).toBe('$pageview')
})

test('ip none', async () => {
    await createPerson(hub, teamId, ['asdfasdfasdf'])

    await processEvent(
        'asdfasdfasdf',
        null,
        '',
        {
            event: '$pageview',
            properties: { distinct_id: 'asdfasdfasdf', token: apiToken },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )
    const [event] = fetchEvents()
    expect(Object.keys(event.properties)).not.toContain('$ip')
})

test('ip capture', async () => {
    await createPerson(hub, teamId, ['asdfasdfasdf'])

    await processEvent(
        'asdfasdfasdf',
        '11.12.13.14',
        '',
        {
            event: '$pageview',
            properties: { distinct_id: 'asdfasdfasdf', token: apiToken },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )
    const [event] = fetchEvents()
    expect(event.properties['$ip']).toBe('11.12.13.14')
})

test('ip override', async () => {
    await createPerson(hub, teamId, ['asdfasdfasdf'])

    await processEvent(
        'asdfasdfasdf',
        '11.12.13.14',
        '',
        {
            event: '$pageview',
            properties: { $ip: '1.0.0.1', distinct_id: 'asdfasdfasdf', token: apiToken },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    const [event] = fetchEvents()
    expect(event.properties['$ip']).toBe('1.0.0.1')
})

test('anonymized ip capture', async () => {
    await hub.db.postgresQuery('update posthog_team set anonymize_ips = $1', [true], 'testTag')
    await createPerson(hub, teamId, ['asdfasdfasdf'])

    await processEvent(
        'asdfasdfasdf',
        '11.12.13.14',
        '',
        {
            event: '$pageview',
            properties: { distinct_id: 'asdfasdfasdf', token: apiToken },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    const [event] = fetchEvents()
    expect(event.properties['$ip']).not.toBeDefined()
})

test('alias', async () => {
    await createPerson(hub, teamId, ['old_distinct_id'])

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$create_alias',
            properties: { distinct_id: 'new_distinct_id', token: apiToken, alias: 'old_distinct_id' },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(fetchEvents().length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues((await fetchPostgresPersons())[0])).toEqual([
        'old_distinct_id',
        'new_distinct_id',
    ])
})

test('alias reverse', async () => {
    await createPerson(hub, teamId, ['old_distinct_id'])

    await processEvent(
        'old_distinct_id',
        '',
        '',
        {
            event: '$create_alias',
            properties: { distinct_id: 'old_distinct_id', token: apiToken, alias: 'new_distinct_id' },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(fetchEvents().length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues((await fetchPostgresPersons())[0])).toEqual([
        'old_distinct_id',
        'new_distinct_id',
    ])
})

test('alias twice', async () => {
    await createPerson(hub, teamId, ['old_distinct_id'])

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$create_alias',
            properties: { distinct_id: 'new_distinct_id', token: apiToken, alias: 'old_distinct_id' },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect((await fetchPostgresPersons()).length).toBe(1)
    expect(fetchEvents().length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues((await fetchPostgresPersons())[0])).toEqual([
        'old_distinct_id',
        'new_distinct_id',
    ])

    await createPerson(hub, teamId, ['old_distinct_id_2'])
    expect((await fetchPostgresPersons()).length).toBe(2)

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$create_alias',
            properties: { distinct_id: 'new_distinct_id', token: apiToken, alias: 'old_distinct_id_2' },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )
    expect(fetchEvents().length).toBe(2)
    expect((await fetchPostgresPersons()).length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues((await fetchPostgresPersons())[0])).toEqual([
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
            properties: { distinct_id: 'new_distinct_id', token: apiToken, alias: 'old_distinct_id' },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(fetchEvents().length).toBe(1)
    expect((await fetchPostgresPersons()).length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues((await fetchPostgresPersons())[0])).toEqual([
        'new_distinct_id',
        'old_distinct_id',
    ])
})

test('alias both existing', async () => {
    await createPerson(hub, teamId, ['old_distinct_id'])
    await createPerson(hub, teamId, ['new_distinct_id'])

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$create_alias',
            properties: { distinct_id: 'new_distinct_id', token: apiToken, alias: 'old_distinct_id' },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(fetchEvents().length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues((await fetchPostgresPersons())[0])).toEqual([
        'old_distinct_id',
        'new_distinct_id',
    ])
})

test('alias merge properties', async () => {
    await createPerson(hub, teamId, ['new_distinct_id'], {
        key_on_both: 'new value both',
        key_on_new: 'new value',
    })
    await createPerson(hub, teamId, ['old_distinct_id'], {
        key_on_both: 'old value both',
        key_on_old: 'old value',
    })

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$create_alias',
            properties: { distinct_id: 'new_distinct_id', token: apiToken, alias: 'old_distinct_id' },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(fetchEvents().length).toBe(1)
    expect((await fetchPostgresPersons()).length).toBe(1)
    const [person] = await fetchPostgresPersons()
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
                token: apiToken,
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
        teamId,
        now,
        new UUIDT().toString()
    )

    const [event] = fetchEvents()
    const [element] = event.elements_chain!
    expect(element.href?.length).toEqual(2048)
    expect(element.text?.length).toEqual(400)
})

test('capture first team event', async () => {
    await hub.db.postgresQuery(`UPDATE posthog_team SET ingested_event = $1 WHERE id = $2`, [false, teamId], 'testTag')

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
                token: apiToken,
                $elements: [{ tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' }],
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(posthog.capture).toHaveBeenCalledWith({
        distinctId: expect.any(String),
        event: 'first team event ingested',
        properties: {
            team: teamUuid,
        },
        groups: {
            project: teamUuid,
            organization: organizationId,
            instance: 'unknown',
        },
    })

    const team = await fetchTeam(hub.postgres, teamId)
    assert(team)

    expect(team.ingested_event).toEqual(true)

    const [event] = fetchEvents()

    const elements = event.elements_chain!
    expect(elements.length).toEqual(1)
})

test('snapshot event stored as session_recording_event', async () => {
    const producer = {
        queueSingleJsonMessage: jest.fn(),
    }

    await createSessionRecordingEvent(
        'some-id',
        teamId,
        '5AzhubH8uMghFHxXq0phfs14JOjH6SA2Ftr1dzXj7U4',
        now,
        '',
        { $session_id: 'abcf-efg', $snapshot_data: { timestamp: 123 } } as any as Properties,
        producer as any as KafkaProducerWrapper
    )

    const [_topic, _uuid, data] = producer.queueSingleJsonMessage.mock.calls[0]

    expect(data).toEqual({
        created_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2} [\d\s:]+/),
        distinct_id: '5AzhubH8uMghFHxXq0phfs14JOjH6SA2Ftr1dzXj7U4',
        session_id: 'abcf-efg',
        snapshot_data: '{"timestamp":123}',
        team_id: teamId,
        timestamp: expect.stringMatching(/^\d{4}-\d{2}-\d{2} [\d\s:]+/),
        uuid: 'some-id',
        window_id: undefined,
    })
})

test('performance event stored as performance_event', async () => {
    const producer = {
        queueSingleJsonMessage: jest.fn(),
    }

    await createPerformanceEvent(
        'some-id',
        teamId,
        '5AzhubH8uMghFHxXq0phfs14JOjH6SA2Ftr1dzXj7U4',
        {
            // Taken from a real event from the JS
            '0': 'resource',
            '1': 1671723295836,
            '2': 'http://localhost:8000/api/projects/1/session_recordings',
            '3': 10737.89999999106,
            '4': 0,
            '5': 0,
            '6': 0,
            '7': 10737.89999999106,
            '8': 10737.89999999106,
            '9': 10737.89999999106,
            '10': 10737.89999999106,
            '11': 0,
            '12': 10737.89999999106,
            '13': 10745.09999999404,
            '14': 11121.70000000298,
            '15': 11122.20000000298,
            '16': 73374,
            '17': 1767,
            '18': 'fetch',
            '19': 'http/1.1',
            '20': 'non-blocking',
            '22': 2067,
            '39': 384.30000001192093,
            '40': 1671723306573,
            token: 'phc_234',
            $session_id: '1853a793ad26c1-0eea05631cbeff-17525635-384000-1853a793ad31dd2',
            $window_id: '1853a793ad424a5-017f7473b057f1-17525635-384000-1853a793ad524dc',
            distinct_id: '5AzhubH8uMghFHxXq0phfs14JOjH6SA2Ftr1dzXj7U4',
            $current_url: 'http://localhost:8000/recordings/recent',
        },
        '',
        now,
        producer as any as KafkaProducerWrapper
    )

    const [_topic, _uuid, data] = producer.queueSingleJsonMessage.mock.calls[0]

    expect(data).toEqual({
        connect_end: 10737.89999999106,
        connect_start: 10737.89999999106,
        current_url: 'http://localhost:8000/recordings/recent',
        decoded_body_size: 73374,
        distinct_id: '5AzhubH8uMghFHxXq0phfs14JOjH6SA2Ftr1dzXj7U4',
        domain_lookup_end: 10737.89999999106,
        domain_lookup_start: 10737.89999999106,
        duration: 384.30000001192093,
        encoded_body_size: 1767,
        entry_type: 'resource',
        fetch_start: 10737.89999999106,
        initiator_type: 'fetch',
        name: 'http://localhost:8000/api/projects/1/session_recordings',
        next_hop_protocol: 'http/1.1',
        pageview_id: undefined,
        redirect_end: 0,
        redirect_start: 0,
        render_blocking_status: 'non-blocking',
        request_start: 10745.09999999404,
        response_end: 11122.20000000298,
        response_start: 11121.70000000298,
        secure_connection_start: 0,
        session_id: '1853a793ad26c1-0eea05631cbeff-17525635-384000-1853a793ad31dd2',
        start_time: 10737.89999999106,
        team_id: teamId,
        time_origin: 1671723295836,
        timestamp: 1671723306573,
        transfer_size: 2067,
        uuid: 'some-id',
        window_id: '1853a793ad424a5-017f7473b057f1-17525635-384000-1853a793ad524dc',
        worker_start: 0,
    })
})

test('identify set', async () => {
    await createPerson(hub, teamId, ['distinct_id1'])
    const ts_before = now
    const ts_after = now.plus({ hours: 1 })

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: '$identify',
            properties: {
                token: apiToken,
                distinct_id: 'distinct_id1',
                $set: { a_prop: 'test-1', c_prop: 'test-1' },
            },
        } as any as PluginEvent,
        teamId,
        ts_before,
        new UUIDT().toString()
    )

    expect(fetchEvents().length).toBe(1)

    const [event] = fetchEvents()
    expect(event.properties['$set']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

    const [person] = await fetchPostgresPersons()
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
                token: apiToken,
                distinct_id: 'distinct_id1',
                $set: { a_prop: 'test-2', b_prop: 'test-2b' },
            },
        } as any as PluginEvent,
        teamId,
        ts_after,
        new UUIDT().toString()
    )
    expect(fetchEvents().length).toBe(2)
    const [person2] = await fetchPostgresPersons()
    expect(person2.properties).toEqual({ a_prop: 'test-2', b_prop: 'test-2b', c_prop: 'test-1' })
})

test('identify set_once', async () => {
    await createPerson(hub, teamId, ['distinct_id1'])

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: '$identify',
            properties: {
                token: apiToken,
                distinct_id: 'distinct_id1',
                $set_once: { a_prop: 'test-1', c_prop: 'test-1' },
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(fetchEvents().length).toBe(1)

    const [event] = fetchEvents()
    expect(event.properties['$set_once']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

    const [person] = await fetchPostgresPersons()
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
                token: apiToken,
                distinct_id: 'distinct_id1',
                $set_once: { a_prop: 'test-2', b_prop: 'test-2b' },
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )
    expect(fetchEvents().length).toBe(2)
    const [person2] = await fetchPostgresPersons()
    expect(person2.properties).toEqual({ a_prop: 'test-1', b_prop: 'test-2b', c_prop: 'test-1' })
    expect(person2.is_identified).toEqual(false)
})

test('identify with illegal (generic) id', async () => {
    await createPerson(hub, teamId, ['im an anonymous id'])
    expect((await fetchPostgresPersons()).length).toBe(1)

    const createPersonAndSendIdentify = async (distinctId: string): Promise<void> => {
        await createPerson(hub, teamId, [distinctId])

        await processEvent(
            distinctId,
            '',
            '',
            {
                event: '$identify',
                properties: {
                    token: apiToken,
                    distinct_id: distinctId,
                    $anon_distinct_id: 'im an anonymous id',
                },
            } as any as PluginEvent,
            teamId,
            now,
            new UUIDT().toString()
        )
    }

    // try to merge, the merge should fail
    await createPersonAndSendIdentify('distinctId')
    expect((await fetchPostgresPersons()).length).toBe(2)

    await createPersonAndSendIdentify('  ')
    expect((await fetchPostgresPersons()).length).toBe(3)

    await createPersonAndSendIdentify('NaN')
    expect((await fetchPostgresPersons()).length).toBe(4)

    await createPersonAndSendIdentify('undefined')
    expect((await fetchPostgresPersons()).length).toBe(5)

    await createPersonAndSendIdentify('None')
    expect((await fetchPostgresPersons()).length).toBe(6)

    await createPersonAndSendIdentify('0')
    expect((await fetchPostgresPersons()).length).toBe(7)

    // 'Nan' is an allowed id, so the merge should work
    // as such, no extra person is created
    await createPersonAndSendIdentify('Nan')
    expect((await fetchPostgresPersons()).length).toBe(7)
})

test('Alias with illegal (generic) id', async () => {
    const legal_id = 'user123'
    const illegal_id = 'null'
    await createPerson(hub, teamId, [legal_id])
    expect((await fetchPostgresPersons()).length).toBe(1)

    await processEvent(
        illegal_id,
        '',
        '',
        {
            event: '$create_alias',
            properties: {
                token: apiToken,
                distinct_id: legal_id,
                alias: illegal_id,
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )
    // person with illegal id got created but not merged
    expect((await fetchPostgresPersons()).length).toBe(2)
})

test('distinct with anonymous_id', async () => {
    await createPerson(hub, teamId, ['anonymous_id'])

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$identify',
            properties: {
                $anon_distinct_id: 'anonymous_id',
                token: apiToken,
                distinct_id: 'new_distinct_id',
                $set: { a_prop: 'test' },
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(fetchEvents().length).toBe(1)
    const [event] = fetchEvents()
    expect(event.properties['$set']).toEqual({ a_prop: 'test' })
    const [person] = await fetchPostgresPersons()
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
                token: apiToken,
                distinct_id: 'new_distinct_id',
                $set: { a_prop: 'test' },
            },
        } as any as PluginEvent,
        teamId,
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
    await createPerson(hub, teamId, ['anonymous_id'])
    await createPerson(hub, teamId, ['new_distinct_id'], { email: 'someone@gmail.com' })

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$identify',
            properties: {
                $anon_distinct_id: 'anonymous_id',
                token: apiToken,
                distinct_id: 'new_distinct_id',
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    const [person] = await fetchPostgresPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['anonymous_id', 'new_distinct_id'])
    expect(person.properties['email']).toEqual('someone@gmail.com')
    expect(person.is_identified).toEqual(true)
})

test('identify with the same distinct_id as anon_distinct_id', async () => {
    await createPerson(hub, teamId, ['anonymous_id'])

    await processEvent(
        'anonymous_id',
        '',
        '',
        {
            event: '$identify',
            properties: {
                $anon_distinct_id: 'anonymous_id',
                token: apiToken,
                distinct_id: 'anonymous_id',
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    const [person] = await fetchPostgresPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['anonymous_id'])
    expect(person.is_identified).toEqual(false)
})

test('distinct with multiple anonymous_ids which were already created', async () => {
    await createPerson(hub, teamId, ['anonymous_id'])
    await createPerson(hub, teamId, ['new_distinct_id'], { email: 'someone@gmail.com' })

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$identify',
            properties: {
                $anon_distinct_id: 'anonymous_id',
                token: apiToken,
                distinct_id: 'new_distinct_id',
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    const persons1 = await fetchPostgresPersons()
    expect(persons1.length).toBe(1)
    expect(await hub.db.fetchDistinctIdValues(persons1[0])).toEqual(['anonymous_id', 'new_distinct_id'])
    expect(persons1[0].properties['email']).toEqual('someone@gmail.com')
    expect(persons1[0].is_identified).toEqual(true)

    await createPerson(hub, teamId, ['anonymous_id_2'])

    await processEvent(
        'new_distinct_id',
        '',
        '',
        {
            event: '$identify',
            properties: {
                $anon_distinct_id: 'anonymous_id_2',
                token: apiToken,
                distinct_id: 'new_distinct_id',
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    const persons2 = await fetchPostgresPersons()
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
    const { teamId: otherTeamId } = await createUserTeamAndOrganization({})
    await createPerson(hub, otherTeamId, ['2'], { email: 'team2@gmail.com' })
    await createPerson(hub, teamId, ['1', '2'])

    await processEvent(
        '2',
        '',
        '',
        {
            event: '$identify',
            properties: {
                $anon_distinct_id: '1',
                token: apiToken,
                distinct_id: '2',
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    const [person] = await fetchPostgresPersons()
    expect(person.team_id).toEqual(teamId)
    expect(person.properties).toEqual({})
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['1', '2'])
    const [otherPerson] = await fetchPostgresPersons(otherTeamId)
    expect(await hub.db.fetchDistinctIdValues(otherPerson)).toEqual(['2'])
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
        const persons = await fetchPostgresPersons()
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
        const persons = await fetchPostgresPersons()
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
        expect(await fetchPostgresPersons()).toEqual([])

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
        const persons = await fetchPostgresPersons()
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
        const persons = await fetchPostgresPersons()
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
        const persons = await fetchPostgresPersons()
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
        const persons = await fetchPostgresPersons()
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
        const persons = await fetchPostgresPersons()
        expect(persons.map((person) => person.is_identified)).toEqual([true])
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

        const persons = await fetchPostgresPersons()
        expect(persons.map((person) => person.is_identified)).toEqual([true])
    })
})

test('team event_properties', async () => {
    expect(await fetchEventDefinitions()).toEqual([])
    expect(await fetchEventProperties()).toEqual([])
    expect(await fetchPropertyDefinitions()).toEqual([])

    await processEvent(
        'xxx',
        '127.0.0.1',
        '',
        { event: 'purchase', properties: { price: 299.99, name: 'AirPods Pro' } } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(await fetchEventDefinitions()).toEqual([
        {
            id: expect.any(String),
            name: 'purchase',
            query_usage_30_day: null,
            team_id: teamId,
            volume_30_day: null,
            created_at: expect.any(String),
            last_seen_at: expect.any(String),
        },
    ])
    expect(await fetchPropertyDefinitions()).toEqual([
        {
            id: expect.any(String),
            is_numerical: false,
            name: '$ip',
            property_type: 'String',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: teamId,
            volume_30_day: null,
            type: PropertyDefinitionTypeEnum.Event,
            group_type_index: null,
        },
        {
            id: expect.any(String),
            is_numerical: false,
            name: 'name',
            property_type: 'String',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: teamId,
            volume_30_day: null,
            type: PropertyDefinitionTypeEnum.Event,
            group_type_index: null,
        },
        {
            id: expect.any(String),
            is_numerical: true,
            name: 'price',
            property_type: 'Numeric',
            property_type_format: null,
            query_usage_30_day: null,
            team_id: teamId,
            volume_30_day: null,
            type: PropertyDefinitionTypeEnum.Event,
            group_type_index: null,
        },
    ])

    // flushed every minute normally, triggering flush now, it's tested elsewhere
    expect(await fetchEventProperties()).toEqual([
        {
            id: expect.any(Number),
            event: 'purchase',
            property: '$ip',
            team_id: teamId,
        },
        {
            id: expect.any(Number),
            event: 'purchase',
            property: 'name',
            team_id: teamId,
        },
        {
            id: expect.any(Number),
            event: 'purchase',
            property: 'price',
            team_id: teamId,
        },
    ])
})

test('event name object json', async () => {
    await processEvent(
        'xxx',
        '',
        '',
        { event: { 'event name': 'as object' }, properties: {} } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )
    const [event] = fetchEvents()
    expect(event.event).toEqual('{"event name":"as object"}')
})

test('event name array json', async () => {
    await processEvent(
        'xxx',
        '',
        '',
        { event: ['event name', 'a list'], properties: {} } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )
    const [event] = fetchEvents()
    expect(event.event).toEqual('["event name","a list"]')
})

test('long event name substr', async () => {
    await processEvent(
        'xxx',
        '',
        '',
        { event: 'E'.repeat(300), properties: { price: 299.99, name: 'AirPods Pro' } } as any as PluginEvent,
        teamId,
        DateTime.utc(),
        new UUIDT().toString()
    )

    const [event] = fetchEvents()
    expect(event.event?.length).toBe(200)
})

test('throws with bad uuid', async () => {
    await expect(
        eventsProcessor.processEvent(
            'xxx',
            '',
            { event: 'E', properties: { price: 299.99, name: 'AirPods Pro' } } as any as PluginEvent,
            teamId,
            DateTime.utc(),
            'this is not an uuid'
        )
    ).rejects.toEqual(new Error('Not a valid UUID: "this is not an uuid"'))

    await expect(
        eventsProcessor.processEvent(
            'xxx',
            '',
            { event: 'E', properties: { price: 299.99, name: 'AirPods Pro' } } as any as PluginEvent,
            teamId,
            DateTime.utc(),
            null as any
        )
    ).rejects.toEqual(new Error('Not a valid UUID: "null"'))
})

test('any event can do $set on props (user exists)', async () => {
    await createPerson(hub, teamId, ['distinct_id1'])

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_event',
            properties: {
                token: apiToken,
                distinct_id: 'distinct_id1',
                $set: { a_prop: 'test-1', c_prop: 'test-1' },
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(fetchEvents().length).toBe(1)

    const [event] = fetchEvents()
    expect(event.properties['$set']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

    const [person] = await fetchPostgresPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
    expect(person.properties).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })
})

test('any event can do $set on props (new user)', async () => {
    const uuid = new UUIDT().toString()

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_event',
            properties: {
                token: apiToken,
                distinct_id: 'distinct_id1',
                $set: { a_prop: 'test-1', c_prop: 'test-1' },
            },
        } as any as PluginEvent,
        teamId,
        now,
        uuid
    )

    expect(fetchEvents().length).toBe(1)

    const [event] = fetchEvents()
    expect(event.properties['$set']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

    const [person] = await fetchPostgresPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
    expect(person.properties).toEqual({ $creator_event_uuid: uuid, a_prop: 'test-1', c_prop: 'test-1' })
})

test('any event can do $set_once on props', async () => {
    await createPerson(hub, teamId, ['distinct_id1'])

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_event',
            properties: {
                token: apiToken,
                distinct_id: 'distinct_id1',
                $set_once: { a_prop: 'test-1', c_prop: 'test-1' },
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(fetchEvents().length).toBe(1)

    const [event] = fetchEvents()
    expect(event.properties['$set_once']).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

    const [person] = await fetchPostgresPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
    expect(person.properties).toEqual({ a_prop: 'test-1', c_prop: 'test-1' })

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_other_event',
            properties: {
                token: apiToken,
                distinct_id: 'distinct_id1',
                $set_once: { a_prop: 'test-2', b_prop: 'test-2b' },
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )
    expect(fetchEvents().length).toBe(2)
    const [person2] = await fetchPostgresPersons()
    expect(person2.properties).toEqual({ a_prop: 'test-1', b_prop: 'test-2b', c_prop: 'test-1' })
})

test('$set and $set_once', async () => {
    const uuid = new UUIDT().toString()
    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_event',
            properties: {
                token: apiToken,
                distinct_id: 'distinct_id1',
                $set: { key1: 'value1', key2: 'value2', key3: 'value4' },
                $set_once: { key1_once: 'value1', key2_once: 'value2', key3_once: 'value4' },
            },
        } as any as PluginEvent,
        teamId,
        now,
        uuid
    )

    expect(fetchEvents().length).toBe(1)

    const [person] = await fetchPostgresPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
    expect(person.properties).toEqual({
        $creator_event_uuid: uuid,
        key1: 'value1',
        key2: 'value2',
        key3: 'value4',
        key1_once: 'value1',
        key2_once: 'value2',
        key3_once: 'value4',
    })
})

test('groupidentify', async () => {
    await createPerson(hub, teamId, ['distinct_id1'])

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: '$groupidentify',
            properties: {
                token: apiToken,
                distinct_id: 'distinct_id1',
                $group_type: 'organization',
                $group_key: 'org::5',
                $group_set: {
                    foo: 'bar',
                },
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    expect(fetchEvents().length).toBe(1)

    const [clickhouseGroup] = fetchClickhouseGroups()
    expect(clickhouseGroup).toEqual({
        group_key: 'org::5',
        group_properties: JSON.stringify({ foo: 'bar' }),
        group_type_index: 0,
        team_id: teamId,
        created_at: expect.any(String),
    })

    const group = await hub.db.fetchGroup(teamId, 0, 'org::5')
    expect(group).toEqual({
        id: expect.any(Number),
        team_id: teamId,
        group_type_index: 0,
        group_key: 'org::5',
        group_properties: { foo: 'bar' },
        created_at: now,
        properties_last_updated_at: {},
        properties_last_operation: {},
        version: 1,
    })
})

test('$groupidentify updating properties', async () => {
    const next: DateTime = now.plus({ minutes: 1 })

    await createPerson(hub, teamId, ['distinct_id1'])
    await hub.db.insertGroup(teamId, 0, 'org::5', { a: 1, b: 2 }, now, {}, {}, 1)

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: '$groupidentify',
            properties: {
                token: apiToken,
                distinct_id: 'distinct_id1',
                $group_type: 'organization',
                $group_key: 'org::5',
                $group_set: {
                    foo: 'bar',
                    a: 3,
                },
            },
        } as any as PluginEvent,
        teamId,
        next,
        new UUIDT().toString()
    )

    expect(fetchEvents().length).toBe(1)

    const [clickhouseGroup] = fetchClickhouseGroups()
    expect(clickhouseGroup).toEqual({
        group_key: 'org::5',
        group_properties: JSON.stringify({ a: 3, b: 2, foo: 'bar' }),
        group_type_index: 0,
        team_id: teamId,
        created_at: expect.any(String),
    })

    const group = await hub.db.fetchGroup(teamId, 0, 'org::5')
    expect(group).toEqual({
        id: expect.any(Number),
        team_id: teamId,
        group_type_index: 0,
        group_key: 'org::5',
        group_properties: { a: 3, b: 2, foo: 'bar' },
        created_at: now,
        properties_last_updated_at: {},
        properties_last_operation: {},
        version: 2,
    })
})

test('person and group properties on events', async () => {
    await createPerson(hub, teamId, ['distinct_id1'], { pineapple: 'on', pizza: 1 })

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: '$groupidentify',
            properties: {
                token: apiToken,
                distinct_id: 'distinct_id1',
                $group_type: 'organization',
                $group_key: 'org:5',
                $group_set: {
                    foo: 'bar',
                },
            },
        } as any as PluginEvent,
        teamId,
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
                token: apiToken,
                distinct_id: 'distinct_id1',
                $group_type: 'second',
                $group_key: 'second_key',
                $group_set: {
                    pineapple: 'yummy',
                },
            },
        } as any as PluginEvent,
        teamId,
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
                token: apiToken,
                distinct_id: 'distinct_id1',
                $set: { new: 5 },
                $group_0: 'org:5',
                $group_1: 'second_key',
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )

    const events = fetchEvents()
    const event = [...events].find((e: any) => e['event'] === 'test event')
    expect(event?.person_properties).toEqual({ pineapple: 'on', pizza: 1, new: 5 })
    expect(event?.group0_properties).toEqual({ foo: 'bar' })
    expect(event?.group1_properties).toEqual({ pineapple: 'yummy' })
})

test('set and set_once on the same key', async () => {
    await createPerson(hub, teamId, ['distinct_id1'])

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_event',
            properties: {
                token: apiToken,
                distinct_id: 'distinct_id1',
                $set: { a_prop: 'test-set' },
                $set_once: { a_prop: 'test-set_once' },
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )
    expect(fetchEvents().length).toBe(1)

    const [event] = fetchEvents()
    expect(event.properties['$set']).toEqual({ a_prop: 'test-set' })
    expect(event.properties['$set_once']).toEqual({ a_prop: 'test-set_once' })

    const [person] = await fetchPostgresPersons()
    expect(await hub.db.fetchDistinctIdValues(person)).toEqual(['distinct_id1'])
    expect(person.properties).toEqual({ a_prop: 'test-set' })
})

test('$unset person property', async () => {
    await createPerson(hub, teamId, ['distinct_id1'], { a: 1, b: 2, c: 3 })

    await processEvent(
        'distinct_id1',
        '',
        '',
        {
            event: 'some_event',
            properties: {
                token: apiToken,
                distinct_id: 'distinct_id1',
                $unset: ['a', 'c'],
            },
        } as any as PluginEvent,
        teamId,
        now,
        new UUIDT().toString()
    )
    const events = fetchEvents()
    expect(events).toHaveLength(1)

    expect(events).toEqual(
        expect.arrayContaining([
            expect.objectContaining({ properties: expect.objectContaining({ $unset: ['a', 'c'] }) }),
        ])
    )

    const [person] = await fetchPostgresPersons()
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
        await createPerson(hub, teamId, ['distinct_id1'])
    })

    async function verifyPersonPropertiesSetCorrectly() {
        expect(fetchEvents()).toHaveLength(4)

        const [person] = await fetchPostgresPersons()
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
            teamId,
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
