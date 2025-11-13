/*
This file contains a bunch of legacy E2E tests mixed with unit tests.

Rather than add tests here, consider improving event-pipeline-integration test suite or adding
unit tests to appropriate classes/functions.
*/
import { KafkaProducerObserver } from '~/tests/helpers/mocks/producer.spy'

import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'
import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { KAFKA_GROUPS } from '~/config/kafka-topics'
import { createRedis } from '~/utils/db/redis'
import { parseRawClickHouseEvent } from '~/utils/event'
import { captureTeamEvent } from '~/utils/posthog'
import { BatchWritingGroupStoreForBatch } from '~/worker/ingestion/groups/batch-writing-group-store'
import { BatchWritingPersonsStoreForBatch } from '~/worker/ingestion/persons/batch-writing-person-store'
import { PersonsStoreForBatch } from '~/worker/ingestion/persons/persons-store-for-batch'

import { createEmitEventStep } from '../../src/ingestion/event-processing/emit-event-step'
import { isOkResult } from '../../src/ingestion/pipelines/results'
import { ClickHouseEvent, Hub, Person, PluginsServerConfig, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { PostgresUse } from '../../src/utils/db/postgres'
import { UUIDT } from '../../src/utils/utils'
import { EventPipelineRunner } from '../../src/worker/ingestion/event-pipeline/runner'
import { PostgresPersonRepository } from '../../src/worker/ingestion/persons/repositories/postgres-person-repository'
import { fetchDistinctIdValues, fetchPersons } from '../../src/worker/ingestion/persons/repositories/test-helpers'
import { EventsProcessor } from '../../src/worker/ingestion/process-event'
import { resetKafka } from '../helpers/kafka'
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
    const personRepository = new PostgresPersonRepository(server.db.postgres)
    const result = await personRepository.createPerson(
        DateTime.utc(),
        properties,
        {},
        {},
        team.id,
        null,
        false,
        new UUIDT().toString(),
        distinctIds.map((distinctId) => ({ distinctId }))
    )
    if (!result.success) {
        throw new Error('Failed to create person')
    }
    await server.db.kafkaProducer.queueMessages(result.messages)
    return result.person
}

async function flushPersonStoreToKafka(hub: Hub, personStore: PersonsStoreForBatch, kafkaAcks: Promise<unknown>[]) {
    const kafkaMessages = await personStore.flush()
    await hub.db.kafkaProducer.queueMessages(kafkaMessages.map((message) => message.topicMessage))
    await hub.db.kafkaProducer.flush()
    await Promise.all(kafkaAcks)
    return kafkaMessages
}

const TEST_CONFIG: Partial<PluginsServerConfig> = {
    LOG_LEVEL: 'info',
}

describe('processEvent', () => {
    let team: Team
    let hub: Hub
    let personRepository: PostgresPersonRepository
    let eventsProcessor: EventsProcessor
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

        const personsStoreForBatch = new BatchWritingPersonsStoreForBatch(
            new PostgresPersonRepository(hub.db.postgres),
            hub.db.kafkaProducer
        )
        const groupStoreForBatch = new BatchWritingGroupStoreForBatch(
            hub.db,
            hub.groupRepository,
            hub.clickhouseGroupRepository
        )
        const runner = new EventPipelineRunner(hub, pluginEvent, null, personsStoreForBatch, groupStoreForBatch)
        const res = await runner.runEventPipeline(pluginEvent, team)
        if (isOkResult(res)) {
            // Use emit event step to emit the event
            const emitEventStep = createEmitEventStep({
                kafkaProducer: hub.kafkaProducer,
                clickhouseJsonEventsTopic: hub.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
            })
            const emitResult = await emitEventStep(res.value)

            // Handle side effects using side effect handling pipeline
            if (isOkResult(emitResult) && emitResult.sideEffects.length > 0) {
                await Promise.allSettled(emitResult.sideEffects)
            }

            await flushPersonStoreToKafka(hub, personsStoreForBatch, res.sideEffects ?? [])
        }
        await groupStoreForBatch.flush()
    }

    // Simple client used to simulate sending events
    // Use state object to simulate stateful clients that keep track of old
    // distinct id, starting with an anonymous one. I've taken posthog-js as
    // the reference implementation.
    let state = { currentDistinctId: 'anonymous_id' }

    let mockProducerObserver: KafkaProducerObserver

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

        hub = await createHub({ ...TEST_CONFIG })
        mockProducerObserver = new KafkaProducerObserver(hub.kafkaProducer)
        mockProducerObserver.resetKafkaProducer()

        personRepository = new PostgresPersonRepository(hub.db.postgres)

        eventsProcessor = new EventsProcessor(hub)
        team = await getFirstTeam(hub)
        now = DateTime.utc()

        const redis = await createRedis(hub, 'ingestion')
        const hooksCacheKey = `@posthog/plugin-server/hooks/${team.id}`
        await redis.del(hooksCacheKey)
        await redis.quit()

        // Always start with an anonymous state
        state = { currentDistinctId: 'anonymous_id' }
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

    type EventsByPerson = [string[], string[]]

    const getEventsByPerson = async (hub: Hub): Promise<EventsByPerson[]> => {
        // Helper function to retrieve events paired with their associated distinct
        // ids
        const persons = await fetchPersons(hub.db.postgres)
        const events = getEventsFromKafka()

        return await Promise.all(
            persons
                .sort((p1, p2) => p1.created_at.diff(p2.created_at).toMillis())
                .map(async (person) => {
                    const distinctIds = await fetchDistinctIdValues(hub.db.postgres, person)

                    return [
                        distinctIds,
                        (events as ClickHouseEvent[])
                            .filter((event) => distinctIds.includes(event.distinct_id))
                            .sort((e1, e2) => e1.timestamp.diff(e2.timestamp).toMillis())
                            .map((event) => event.event),
                    ] as EventsByPerson
                })
        )
    }

    const capture = async (
        hub: Hub,
        eventName: string,
        properties: any = {},
        personRepository?: PostgresPersonRepository
    ) => {
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
        const personsStoreForBatch = new BatchWritingPersonsStoreForBatch(
            personRepository || new PostgresPersonRepository(hub.db.postgres),
            hub.db.kafkaProducer
        )
        const groupStoreForBatch = new BatchWritingGroupStoreForBatch(
            hub.db,
            hub.groupRepository,
            hub.clickhouseGroupRepository
        )
        const runner = new EventPipelineRunner(hub, event, null, personsStoreForBatch, groupStoreForBatch)
        const res = await runner.runEventPipeline(event, team)
        if (isOkResult(res)) {
            // Use emit event step to emit the event
            const emitEventStep = createEmitEventStep({
                kafkaProducer: hub.kafkaProducer,
                clickhouseJsonEventsTopic: hub.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
            })
            const emitResult = await emitEventStep(res.value)

            // Handle side effects using side effect handling pipeline
            if (isOkResult(emitResult) && emitResult.sideEffects.length > 0) {
                await Promise.allSettled(emitResult.sideEffects)
            }

            await flushPersonStoreToKafka(hub, personsStoreForBatch, res.sideEffects ?? [])
        }
        await groupStoreForBatch.flush()
    }

    const identify = async (hub: Hub, distinctId: string, personRepository?: PostgresPersonRepository) => {
        // Update currentDistinctId state immediately, as the event will be
        // dispatch asynchronously
        const currentDistinctId = state.currentDistinctId
        state.currentDistinctId = distinctId
        await capture(
            hub,
            '$identify',
            {
                // posthog-js will send the previous distinct id as
                // $anon_distinct_id
                $anon_distinct_id: currentDistinctId,
                distinct_id: distinctId,
            },
            personRepository
        )
    }

    const alias = async (hub: Hub, alias: string, distinctId: string) => {
        await capture(hub, '$create_alias', { alias, disinct_id: distinctId })
    }

    test('capture bad team', async () => {
        const groupStoreForBatch = new BatchWritingGroupStoreForBatch(
            hub.db,
            hub.groupRepository,
            hub.clickhouseGroupRepository
        )
        await expect(
            eventsProcessor.processEvent(
                'asdfasdfasdf',
                {
                    event: '$pageview',
                    properties: { distinct_id: 'asdfasdfasdf', token: team.api_token },
                } as any as PluginEvent,
                1337,
                now,
                new UUIDT().toString(),
                false,
                groupStoreForBatch
            )
        ).rejects.toThrow("No team found with ID 1337. Can't ingest event.")
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
        const [event] = getEventsFromKafka()
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
        const [event] = getEventsFromKafka()
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

        const [event] = getEventsFromKafka()
        expect(event.properties['$ip']).toBe('1.0.0.1')
    })

    test('anonymized ip capture', async () => {
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            'update posthog_team set anonymize_ips = $1',
            [true],
            'testTag'
        )
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

        const [event] = getEventsFromKafka()
        expect(event.properties['$ip']).not.toBeTruthy()
    })

    test('merge_dangerously', async () => {
        await createPerson(hub, team, ['old_distinct_id'])

        await processEvent(
            'new_distinct_id',
            '',
            '',
            {
                event: '$merge_dangerously',
                properties: { distinct_id: 'new_distinct_id', token: team.api_token, alias: 'old_distinct_id' },
            } as any as PluginEvent,
            team.id,
            now,
            new UUIDT().toString()
        )

        expect(await fetchDistinctIdValues(hub.db.postgres, (await fetchPersons(hub.db.postgres))[0])).toEqual([
            'old_distinct_id',
            'new_distinct_id',
        ])
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

        expect(await fetchDistinctIdValues(hub.db.postgres, (await fetchPersons(hub.db.postgres))[0])).toEqual([
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

        expect(await fetchDistinctIdValues(hub.db.postgres, (await fetchPersons(hub.db.postgres))[0])).toEqual([
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

        expect((await fetchPersons(hub.db.postgres)).length).toBe(1)
        expect(await fetchDistinctIdValues(hub.db.postgres, (await fetchPersons(hub.db.postgres))[0])).toEqual([
            'old_distinct_id',
            'new_distinct_id',
        ])

        await createPerson(hub, team, ['old_distinct_id_2'])
        expect((await fetchPersons(hub.db.postgres)).length).toBe(2)

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
        expect((await fetchPersons(hub.db.postgres)).length).toBe(1)
        expect(await fetchDistinctIdValues(hub.db.postgres, (await fetchPersons(hub.db.postgres))[0])).toEqual([
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

        expect((await fetchPersons(hub.db.postgres)).length).toBe(1)
        const distinctIds = await fetchDistinctIdValues(hub.db.postgres, (await fetchPersons(hub.db.postgres))[0])
        expect(distinctIds).toEqual(expect.arrayContaining(['new_distinct_id', 'old_distinct_id']))
        expect(distinctIds).toHaveLength(2)
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

        expect(await fetchDistinctIdValues(hub.db.postgres, (await fetchPersons(hub.db.postgres))[0])).toEqual([
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

        expect((await fetchPersons(hub.db.postgres)).length).toBe(1)
        const [person] = await fetchPersons(hub.db.postgres)
        expect((await fetchDistinctIdValues(hub.db.postgres, person)).sort()).toEqual([
            'new_distinct_id',
            'old_distinct_id',
        ])
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

        const [event] = getEventsFromKafka()
        const [element] = event.elements_chain!
        expect(element.href?.length).toEqual(2048)
        expect(element.text?.length).toEqual(400)
    })

    test('capture first team event', async () => {
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_team
            SET ingested_event = $1
            WHERE id = $2`,
            [false, team.id],
            'testTag'
        )

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

    test('identify with illegal (generic) id', async () => {
        await createPerson(hub, team, ['im an anonymous id'])
        expect((await fetchPersons(hub.db.postgres)).length).toBe(1)

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
        expect((await fetchPersons(hub.db.postgres)).length).toBe(2)

        await createPersonAndSendIdentify('  ')
        expect((await fetchPersons(hub.db.postgres)).length).toBe(3)

        await createPersonAndSendIdentify('NaN')
        expect((await fetchPersons(hub.db.postgres)).length).toBe(4)

        await createPersonAndSendIdentify('undefined')
        expect((await fetchPersons(hub.db.postgres)).length).toBe(5)

        await createPersonAndSendIdentify('None')
        expect((await fetchPersons(hub.db.postgres)).length).toBe(6)

        await createPersonAndSendIdentify('0')
        expect((await fetchPersons(hub.db.postgres)).length).toBe(7)

        // 'Nan' is an allowed id, so the merge should work
        // as such, no extra person is created
        await createPersonAndSendIdentify('Nan')
        expect((await fetchPersons(hub.db.postgres)).length).toBe(7)
    })

    test('Alias with illegal (generic) id', async () => {
        const legal_id = 'user123'
        const illegal_id = 'null'
        await createPerson(hub, team, [legal_id])
        expect((await fetchPersons(hub.db.postgres)).length).toBe(1)

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
        expect((await fetchPersons(hub.db.postgres)).length).toBe(2)
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

        const [person] = await fetchPersons(hub.db.postgres)
        expect(await fetchDistinctIdValues(hub.db.postgres, person)).toEqual(['anonymous_id', 'new_distinct_id'])
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

        const [person] = await fetchPersons(hub.db.postgres)
        expect(await fetchDistinctIdValues(hub.db.postgres, person)).toEqual(['anonymous_id'])
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

        const persons1 = await fetchPersons(hub.db.postgres)
        expect(persons1.length).toBe(1)
        expect(await fetchDistinctIdValues(hub.db.postgres, persons1[0])).toEqual(['anonymous_id', 'new_distinct_id'])
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

        const persons2 = await fetchPersons(hub.db.postgres)
        expect(persons2.length).toBe(1)
        expect(await fetchDistinctIdValues(hub.db.postgres, persons2[0])).toEqual([
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

        const people = (await fetchPersons(hub.db.postgres)).sort((p1, p2) => p2.team_id - p1.team_id)
        expect(people.length).toEqual(2)
        expect(people[1].team_id).toEqual(team.id)
        expect(people[1].properties).toEqual({})
        const distinctIdsForPerson1 = await fetchDistinctIdValues(hub.db.postgres, people[1])
        expect(distinctIdsForPerson1).toEqual(expect.arrayContaining(['1', '2']))
        expect(distinctIdsForPerson1).toHaveLength(2)
        expect(people[0].team_id).toEqual(team2.id)
        expect(await fetchDistinctIdValues(hub.db.postgres, people[0])).toEqual(['2'])
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
            const persons = await fetchPersons(hub.db.postgres)
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

            expect(eventsByPerson).toHaveLength(2)
            expect(eventsByPerson[0][0]).toEqual(expect.arrayContaining([initialDistinctId, anonymousId]))
            expect(eventsByPerson[0][0]).toHaveLength(2)
            expect(eventsByPerson[0][1]).toEqual(['$identify', 'event 2', '$identify'])
            expect(eventsByPerson[1][0]).toEqual(expect.arrayContaining([p2DistinctId, p2NewDistinctId]))
            expect(eventsByPerson[1][0]).toHaveLength(2)
            expect(eventsByPerson[1][1]).toEqual(['event 3', '$identify', 'event 4'])

            // Make sure the persons are identified
            const persons = await fetchPersons(hub.db.postgres)
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
            expect(await fetchPersons(hub.db.postgres)).toEqual([])

            const anonymousId = 'anonymous_id'
            const initialDistinctId = 'initial-distinct-id'
            const newDistinctId = 'new-distinct-id'

            state.currentDistinctId = newDistinctId
            await capture(hub, 'some event')
            state.currentDistinctId = anonymousId

            // Hook into createPerson, which is as of writing called from
            // alias. Here we simply call identify again and wait on it
            // completing before continuing with the first identify.
            const originalCreatePerson = personRepository.createPerson.bind(personRepository)
            const createPersonMock = jest.fn(async (...args) => {
                // We need to slice off the txn arg, or else we conflict with the `identify` below.
                // @ts-expect-error because TS is crazy, this is valid
                const result = await originalCreatePerson(...args.slice(0, -1))

                if (createPersonMock.mock.calls.length === 1) {
                    // On second invocation, make another identify call
                    await identify(hub, newDistinctId, personRepository)
                }

                return result
            })
            personRepository.createPerson = createPersonMock

            // set the first identify going
            await identify(hub, initialDistinctId, personRepository)

            // Let's first just make sure `updatePerson` was called, as a way of
            // checking that our mocking was actually invoked
            expect(personRepository.createPerson).toHaveBeenCalled()

            // Now make sure that we have one person in the db that has been
            // identified
            const persons = await fetchPersons(hub.db.postgres)
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
            const persons = await fetchPersons(hub.db.postgres)
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
            expect(eventsByPerson).toHaveLength(1)
            expect(eventsByPerson[0][0]).toEqual(expect.arrayContaining([initialDistinctId, anonymousId]))
            expect(eventsByPerson[0][0]).toHaveLength(2)
            expect(eventsByPerson[0][1]).toEqual(['$identify', 'anonymous event', '$create_alias'])

            // Make sure there is one identified person
            const persons = await fetchPersons(hub.db.postgres)
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
            expect(eventsByPerson).toHaveLength(1)
            expect(eventsByPerson[0][0]).toEqual(expect.arrayContaining([initialDistinctId, anonymousId]))
            expect(eventsByPerson[0][0]).toHaveLength(2)
            expect(eventsByPerson[0][1]).toEqual(['$identify', 'anonymous event', '$create_alias'])

            // Make sure there is one identified person
            const persons = await fetchPersons(hub.db.postgres)
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
            const persons = await fetchPersons(hub.db.postgres)
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
            expect(eventsByPerson).toHaveLength(1)
            expect(eventsByPerson[0][0]).toEqual(expect.arrayContaining([anonymous1, anonymous2]))
            expect(eventsByPerson[0][0]).toHaveLength(2)
            expect(eventsByPerson[0][1]).toEqual(['$create_alias'])

            const persons = await fetchPersons(hub.db.postgres)
            expect(persons.map((person) => person.is_identified)).toEqual([true])
        })
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

    test('person and group properties on events', async () => {
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

        const events = getEventsFromKafka()
        const event = [...events].find((e: any) => e['event'] === 'test event')
        expect(event?.person_properties).toEqual({ pineapple: 'on', pizza: 1, new: 5 })
        expect(event?.properties.$group_0).toEqual('org:5')
        expect(event?.properties.$group_1).toEqual('second_key')
        expect(event?.group0_properties).toEqual({}) // We stopped writing these to the event as queries don't use them
        expect(event?.group1_properties).toEqual({}) // We stopped writing these to the event as queries don't use them
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

        const [event] = getEventsFromKafka()
        expect(event.properties['$set']).toEqual({ a_prop: 'test-set' })
        expect(event.properties['$set_once']).toEqual({ a_prop: 'test-set_once' })

        const [person] = await fetchPersons(hub.db.postgres)
        expect(await fetchDistinctIdValues(hub.db.postgres, person)).toEqual(['distinct_id1'])
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

        const [event] = getEventsFromKafka()
        expect(event.properties['$unset']).toEqual(['a', 'c'])

        const [person] = await fetchPersons(hub.db.postgres)
        expect(await fetchDistinctIdValues(hub.db.postgres, person)).toEqual(['distinct_id1'])
        expect(person.properties).toEqual({ b: 2 })
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

        const [person] = await fetchPersons(hub.db.postgres)
        expect(await fetchDistinctIdValues(hub.db.postgres, person)).toEqual(['distinct_id1'])
        expect(person.properties).toEqual({ a: 1, b: 2, c: 3 })
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
            const [person] = await fetchPersons(hub.db.postgres)
            expect(await fetchDistinctIdValues(hub.db.postgres, person)).toEqual(['distinct_id1'])
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
})
