/*
This file contains a bunch of legacy E2E tests mixed with unit tests.

Rather than add tests here, consider improving event-pipeline-integration test suite or adding
unit tests to appropriate classes/functions.
*/
import { KafkaProducerObserver } from '~/tests/helpers/mocks/producer.spy'

import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { KAFKA_GROUPS } from '~/config/kafka-topics'
import { createRedisFromConfig } from '~/utils/db/redis'
import { parseRawClickHouseEvent } from '~/utils/event'
import { captureTeamEvent } from '~/utils/posthog'
import { BatchWritingGroupStoreForBatch } from '~/worker/ingestion/groups/batch-writing-group-store'
import { BatchWritingPersonsStore } from '~/worker/ingestion/persons/batch-writing-person-store'
import { PersonsStore } from '~/worker/ingestion/persons/persons-store'

import { createCreateEventStep } from '../../src/ingestion/event-processing/create-event-step'
import { createEmitEventStep } from '../../src/ingestion/event-processing/emit-event-step'
import { isOkResult } from '../../src/ingestion/pipelines/results'
import { Hub, Person, PluginsServerConfig, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { PostgresUse } from '../../src/utils/db/postgres'
import { UUIDT } from '../../src/utils/utils'
import { EventPipelineRunner } from '../../src/worker/ingestion/event-pipeline/runner'
import { PostgresPersonRepository } from '../../src/worker/ingestion/persons/repositories/postgres-person-repository'
import { fetchDistinctIdValues, fetchPersons } from '../../src/worker/ingestion/persons/repositories/test-helpers'
import { createTestEventHeaders } from '../helpers/event-headers'
import { resetKafka } from '../helpers/kafka'
import { createTestMessage } from '../helpers/kafka-message'
import { createTestPerson } from '../helpers/person'
import { createUserTeamAndOrganization, getFirstTeam, getTeams, resetTestDatabase } from '../helpers/sql'

jest.mock('../../src/utils/logger')
jest.setTimeout(600000) // 600 sec timeout.
jest.mock('../../src/utils/posthog', () => ({
    ...jest.requireActual('../../src/utils/posthog'),
    captureTeamEvent: jest.fn(),
}))

export async function createPerson(
    server: Hub,
    team: Team,
    distinctIds: string[],
    properties: Record<string, any> = {}
): Promise<Person> {
    const personRepository = new PostgresPersonRepository(server.postgres)
    const [primaryDistinctId, ...extraDistinctIds] = distinctIds.map((distinctId) => ({ distinctId }))
    const result = await personRepository.createPerson(
        DateTime.utc(),
        properties,
        {},
        {},
        team.id,
        null,
        false,
        new UUIDT().toString(),
        primaryDistinctId,
        extraDistinctIds
    )
    if (!result.success) {
        throw new Error('Failed to create person')
    }
    await server.kafkaProducer.queueMessages(result.messages)
    return result.person
}

async function flushPersonStoreToKafka(hub: Hub, personStore: PersonsStore, kafkaAcks: Promise<unknown>[]) {
    const kafkaMessages = await personStore.flush()
    await hub.kafkaProducer.queueMessages(kafkaMessages.map((message) => message.topicMessage))
    await hub.kafkaProducer.flush()
    await Promise.all(kafkaAcks)
    return kafkaMessages
}

const TEST_CONFIG: Partial<PluginsServerConfig> = {
    LOG_LEVEL: 'info',
}

describe('processEvent', () => {
    let team: Team
    let hub: Hub
    let now = DateTime.utc()

    async function processEvent(
        distinctId: string,
        ip: string | null,
        _siteUrl: string,
        data: Partial<PluginEvent>,
        teamId: number,
        timestamp: DateTime,
        eventUuid: string
    ): Promise<void> {
        const normalizedEvent: PluginEvent = {
            distinct_id: distinctId,
            site_url: _siteUrl,
            team_id: teamId,
            timestamp: timestamp.toUTC().toISO()!,
            now: timestamp.toUTC().toISO()!,
            ip: null,
            uuid: eventUuid,
            properties: { $ip: ip },
            event: 'default event',
            ...data,
        }
        const eventTimestamp = timestamp.toUTC()

        const personsStoreForBatch = new BatchWritingPersonsStore(
            new PostgresPersonRepository(hub.postgres),
            hub.kafkaProducer
        )
        const groupStoreForBatch = new BatchWritingGroupStoreForBatch(
            hub.kafkaProducer,
            hub.groupRepository,
            hub.clickhouseGroupRepository
        )
        const person = createTestPerson({ team_id: teamId })

        const runner = new EventPipelineRunner(
            {
                SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: hub.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP,
                TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE: hub.TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE,
                PIPELINE_STEP_STALLED_LOG_TIMEOUT: hub.PIPELINE_STEP_STALLED_LOG_TIMEOUT,
                PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: hub.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
                PERSON_MERGE_ASYNC_ENABLED: hub.PERSON_MERGE_ASYNC_ENABLED,
                PERSON_MERGE_ASYNC_TOPIC: hub.PERSON_MERGE_ASYNC_TOPIC,
                PERSON_MERGE_SYNC_BATCH_SIZE: hub.PERSON_MERGE_SYNC_BATCH_SIZE,
                PERSON_JSONB_SIZE_ESTIMATE_ENABLE: hub.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
                PERSON_PROPERTIES_UPDATE_ALL: hub.PERSON_PROPERTIES_UPDATE_ALL,
            },
            hub.kafkaProducer,
            hub.teamManager,
            hub.groupTypeManager,
            normalizedEvent,
            groupStoreForBatch
        )
        const res = await runner.runEventPipeline(normalizedEvent, eventTimestamp, team, true, person)
        if (isOkResult(res)) {
            const createEventStep = createCreateEventStep()
            const { person, preparedEvent, processPerson, historicalMigration } = res.value
            const createResult = await createEventStep({
                person,
                preparedEvent,
                processPerson,
                historicalMigration,
                inputHeaders: createTestEventHeaders(),
                inputMessage: createTestMessage(),
            })

            if (isOkResult(createResult)) {
                const emitEventStep = createEmitEventStep({
                    kafkaProducer: hub.kafkaProducer,
                    clickhouseJsonEventsTopic: hub.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                    groupId: 'test-group-id',
                })
                const emitResult = await emitEventStep(createResult.value)

                if (isOkResult(emitResult) && emitResult.sideEffects.length > 0) {
                    await Promise.allSettled(emitResult.sideEffects)
                }
            }

            await flushPersonStoreToKafka(hub, personsStoreForBatch, res.sideEffects ?? [])
        }
        await groupStoreForBatch.flush()
    }

    let mockProducerObserver: KafkaProducerObserver

    beforeAll(async () => {
        await resetKafka(TEST_CONFIG)
    })

    beforeEach(async () => {
        await resetTestDatabase()

        hub = await createHub({ ...TEST_CONFIG })
        mockProducerObserver = new KafkaProducerObserver(hub.kafkaProducer)
        mockProducerObserver.resetKafkaProducer()

        team = await getFirstTeam(hub)
        now = DateTime.utc()

        const redis = await createRedisFromConfig(
            hub.INGESTION_REDIS_HOST
                ? { url: hub.INGESTION_REDIS_HOST, options: { port: hub.INGESTION_REDIS_PORT } }
                : hub.POSTHOG_REDIS_HOST
                  ? {
                        url: hub.POSTHOG_REDIS_HOST,
                        options: { port: hub.POSTHOG_REDIS_PORT, password: hub.POSTHOG_REDIS_PASSWORD },
                    }
                  : { url: hub.REDIS_URL }
        )
        const hooksCacheKey = `@posthog/plugin-server/hooks/${team.id}`
        await redis.del(hooksCacheKey)
        await redis.quit()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    const getEventsFromKafka = (): Record<string, any>[] => {
        const events = mockProducerObserver
            .getProducedKafkaMessagesForTopic(hub.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC)
            .map((x) => parseRawClickHouseEvent(x.value as any))

        return events
    }

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
        const [event] = getEventsFromKafka()
        expect(Object.keys(event.properties)).not.toContain('$ip')
    })

    test('anonymized ip capture', async () => {
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            'update posthog_team set anonymize_ips = $1',
            [true],
            'testTag'
        )
        team = await getFirstTeam(hub)
        await createPerson(hub, team, ['asdfasdfasdf'])

        await processEvent(
            'asdfasdfasdf',
            null,
            '',
            {
                event: '$pageview',
                properties: { distinct_id: 'asdfasdfasdf', token: team.api_token, $ip: '11.12.13.14' },
            } as any as PluginEvent,
            team.id,
            now,
            new UUIDT().toString()
        )

        const [event] = getEventsFromKafka()
        expect(event.properties['$ip']).not.toBeTruthy()
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

        const [event] = getEventsFromKafka()
        const [element] = event.elements_chain!
        expect(element.href?.length).toEqual(2048)
        expect(element.text?.length).toEqual(400)
    })

    test('capture first team event', async () => {
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_team
            SET ingested_event = $1
            WHERE id = $2`,
            [false, team.id],
            'testTag'
        )
        team = await getFirstTeam(hub)

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

        expect(captureTeamEvent).toHaveBeenCalledWith(
            expect.objectContaining({ uuid: team.uuid, organization_id: team.organization_id }),
            'first team event ingested',
            { host: undefined, realm: undefined, sdk: undefined },
            'plugin_test_user_distinct_id_1001'
        )

        team = await getFirstTeam(hub)
        expect(team.ingested_event).toEqual(true)

        const [event] = getEventsFromKafka()

        const elements = event.elements_chain!
        expect(elements.length).toEqual(1)
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

        const [person] = await fetchPersons(hub.postgres)
        expect(await fetchDistinctIdValues(hub.postgres, person)).toEqual(['anonymous_id'])
        expect(person.is_identified).toEqual(false)
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

        const people = (await fetchPersons(hub.postgres)).sort((p1, p2) => p2.team_id - p1.team_id)
        expect(people.length).toEqual(2)
        expect(people[1].team_id).toEqual(team.id)
        expect(people[1].properties).toEqual({})
        const distinctIdsForPerson1 = await fetchDistinctIdValues(hub.postgres, people[1])
        expect(distinctIdsForPerson1).toEqual(expect.arrayContaining(['1', '2']))
        expect(distinctIdsForPerson1).toHaveLength(2)
        expect(people[0].team_id).toEqual(team2.id)
        expect(await fetchDistinctIdValues(hub.postgres, people[0])).toEqual(['2'])
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
        const [event] = getEventsFromKafka()
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
        const [event] = getEventsFromKafka()
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

        const [event] = getEventsFromKafka()
        expect(event.event?.length).toBe(200)
    })

    test('groupidentify without group_type ingests event', async () => {
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
    })

    test('$groupidentify updating properties', async () => {
        const next: DateTime = now.plus({ minutes: 1 })

        await createPerson(hub, team, ['distinct_id1'])
        await hub.groupRepository.insertGroup(team.id, 0, 'org::5', { a: 1, b: 2 }, now, {}, {})

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

        expect(mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_GROUPS)[0].value).toEqual({
            group_key: 'org::5',
            group_properties: JSON.stringify({ a: 3, b: 2, foo: 'bar' }),
            group_type_index: 0,
            team_id: team.id,
            created_at: expect.any(String),
            version: 2,
        })

        const group = await hub.groupRepository.fetchGroup(team.id, 0, 'org::5')
        expect(group).toEqual({
            id: expect.any(Number),
            team_id: team.id,
            group_type_index: 0,
            group_key: 'org::5',
            group_properties: { a: 3, b: 2, foo: 'bar' },
            created_at: now,
            properties_last_updated_at: {},
            properties_last_operation: {},
            version: 2,
        })
    })

    test('$unset person empty set ignored', async () => {
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
                    $unset: {},
                },
            } as any as PluginEvent,
            team.id,
            now,
            new UUIDT().toString()
        )

        const [event] = getEventsFromKafka()
        expect(event.properties['$unset']).toEqual({})

        const [person] = await fetchPersons(hub.postgres)
        expect(await fetchDistinctIdValues(hub.postgres, person)).toEqual(['distinct_id1'])
        expect(person.properties).toEqual({ a: 1, b: 2, c: 3 })
    })
})
