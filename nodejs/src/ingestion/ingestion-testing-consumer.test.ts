import { mockProducer, mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { forSnapshot } from '~/tests/helpers/snapshots'
import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, PipelineEvent, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { UUIDT } from '../utils/utils'
import { IngestionTestingConsumer } from './ingestion-testing-consumer'

const DEFAULT_TEST_TIMEOUT = 5000
jest.setTimeout(DEFAULT_TEST_TIMEOUT)

jest.mock('../utils/posthog', () => {
    const original = jest.requireActual('../utils/posthog')
    return {
        ...original,
        captureException: jest.fn(),
    }
})

// Mock the IngestionWarningLimiter to always allow warnings (prevents rate limiting between tests)
jest.mock('../utils/token-bucket', () => {
    const mockConsume = jest.fn().mockReturnValue(true)
    return {
        ...jest.requireActual('../utils/token-bucket'),
        IngestionWarningLimiter: {
            consume: mockConsume,
        },
    }
})

let offsetIncrementer = 0

const createKafkaMessage = (event: PipelineEvent, token: string): Message => {
    const captureEvent = {
        uuid: event.uuid,
        distinct_id: event.distinct_id,
        ip: event.ip,
        now: event.now,
        token,
        data: JSON.stringify(event),
    }
    return {
        key: `${token}:${event.distinct_id}`,
        value: Buffer.from(JSON.stringify(captureEvent)),
        size: 1,
        topic: 'test',
        offset: offsetIncrementer++,
        timestamp: DateTime.now().toMillis(),
        partition: 1,
        headers: [
            {
                distinct_id: Buffer.from(event.distinct_id || ''),
            },
            {
                token: Buffer.from(token),
            },
            {
                event: Buffer.from(event.event || ''),
            },
            {
                uuid: Buffer.from(event.uuid || ''),
            },
            {
                now: Buffer.from(event.now || ''),
            },
        ],
    }
}

describe('IngestionTestingConsumer', () => {
    let ingester: IngestionTestingConsumer
    let hub: Hub
    let team: Team
    let team2: Team
    let fixedTime: DateTime

    const createIngestionTestingConsumer = async (
        hub: Hub,
        overrides?: ConstructorParameters<typeof IngestionTestingConsumer>[2]
    ) => {
        const ingester = new IngestionTestingConsumer(hub, { ...hub, kafkaProducer: mockProducer }, overrides)
        // NOTE: We don't actually use kafka so we skip instantiation for faster tests
        ingester['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn(),
        } as any
        await ingester.start()
        return ingester
    }

    const createEvent = (event?: Partial<PipelineEvent>): PipelineEvent => ({
        distinct_id: 'user-1',
        uuid: new UUIDT().toString(),
        ip: '127.0.0.1',
        site_url: 'us.posthog.com',
        now: fixedTime.toISO()!,
        event: '$pageview',
        ...event,
        properties: {
            $current_url: 'http://localhost:8000',
            ...(event?.properties || {}),
        },
    })

    const createKafkaMessages = (events: PipelineEvent[], token?: string): Message[] => {
        return events.map((event) => createKafkaMessage(event, token ?? team.api_token))
    }

    beforeEach(async () => {
        fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        jest.spyOn(Date.prototype, 'toISOString').mockReturnValue(fixedTime.toISO()!)

        offsetIncrementer = 0
        await resetTestDatabase()
        hub = await createHub()

        team = await getFirstTeam(hub.postgres)
        const team2Id = await createTeam(hub.postgres, team.organization_id, 'THIS IS NOT A TOKEN FOR TEAM 3')
        team2 = (await getTeam(hub.postgres, team2Id))!

        ingester = await createIngestionTestingConsumer(hub)
    })

    afterEach(async () => {
        await ingester.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('general', () => {
        it('should have the correct config', () => {
            expect(ingester['name']).toMatchInlineSnapshot(`"ingestion-testing-consumer-events_plugin_ingestion_test"`)
            expect(ingester['groupId']).toMatchInlineSnapshot(`"events-ingestion-consumer"`)
            expect(ingester['topic']).toMatchInlineSnapshot(`"events_plugin_ingestion_test"`)
            expect(ingester['dlqTopic']).toMatchInlineSnapshot(`"events_plugin_ingestion_dlq_test"`)
        })

        it('should process a standard event', async () => {
            await ingester.handleKafkaBatch(createKafkaMessages([createEvent()]))

            expect(forSnapshot(mockProducerObserver.getProducedKafkaMessages())).toMatchSnapshot()
        })

        it('should process multiple events', async () => {
            const events = [
                createEvent({ distinct_id: 'user-1' }),
                createEvent({ distinct_id: 'user-2' }),
                createEvent({ distinct_id: 'user-1', event: '$identify' }),
            ]
            await ingester.handleKafkaBatch(createKafkaMessages(events))

            const producedMessages =
                mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(producedMessages).toHaveLength(3)
        })

        it('should not produce person-related kafka messages', async () => {
            // Send an event with $set properties that would normally trigger person updates
            const events = [
                createEvent({
                    properties: {
                        $current_url: 'http://localhost:8000',
                        $set: { email: 'test@test.com' },
                        $set_once: { first_seen: '2025-01-01' },
                    },
                }),
            ]
            await ingester.handleKafkaBatch(createKafkaMessages(events))

            const allMessages = mockProducerObserver.getProducedKafkaMessages()

            // Should have event messages but NO person messages
            const personMessages = allMessages.filter(
                (m) =>
                    m.topic === 'clickhouse_person_test' ||
                    m.topic === 'clickhouse_person_distinct_id2_test' ||
                    m.topic === 'clickhouse_person_unique_id_test'
            )
            expect(personMessages).toHaveLength(0)

            // Should still produce the event itself
            const eventMessages = allMessages.filter((m) => m.topic === 'clickhouse_events_json_test')
            expect(eventMessages).toHaveLength(1)
        })

        it('should not produce group-related kafka messages for $groupidentify', async () => {
            const events = [
                createEvent({
                    event: '$groupidentify',
                    properties: {
                        $group_type: 'company',
                        $group_key: 'posthog',
                        $group_set: { name: 'PostHog' },
                    },
                }),
            ]
            await ingester.handleKafkaBatch(createKafkaMessages(events))

            const allMessages = mockProducerObserver.getProducedKafkaMessages()

            // Should NOT produce group messages
            const groupMessages = allMessages.filter((m) => m.topic === 'clickhouse_groups_test')
            expect(groupMessages).toHaveLength(0)

            // Should still produce the event itself
            const eventMessages = allMessages.filter((m) => m.topic === 'clickhouse_events_json_test')
            expect(eventMessages).toHaveLength(1)
        })

        it('should set processPerson to false in produced events', async () => {
            await ingester.handleKafkaBatch(createKafkaMessages([createEvent()]))

            const eventMessages = mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(eventMessages).toHaveLength(1)

            const eventData = eventMessages[0].value
            expect(eventData.person_mode).toBe('propertyless')
        })

        it('should use a deterministic fake person uuid', async () => {
            // Send two events for the same user
            const events = [createEvent({ distinct_id: 'user-1' }), createEvent({ distinct_id: 'user-1' })]
            await ingester.handleKafkaBatch(createKafkaMessages(events))

            const eventMessages = mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(eventMessages).toHaveLength(2)

            // Both events should have the same person_id (deterministic from team_id + distinct_id)
            expect(eventMessages[0].value.person_id).toBe(eventMessages[1].value.person_id)
        })

        it('should drop events with invalid token', async () => {
            await ingester.handleKafkaBatch(createKafkaMessages([createEvent()], 'invalid-token'))

            const eventMessages = mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(eventMessages).toHaveLength(0)
        })

        it('should process events from multiple teams', async () => {
            const events1 = createKafkaMessages([createEvent()], team.api_token)
            const events2 = createKafkaMessages([createEvent()], team2.api_token)
            await ingester.handleKafkaBatch([...events1, ...events2])

            const eventMessages = mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(eventMessages).toHaveLength(2)

            const teamIds = eventMessages.map((m) => m.value.team_id)
            expect(teamIds).toContain(team.id)
            expect(teamIds).toContain(team2.id)
        })
    })

    describe('client ingestion warnings', () => {
        it('should process client ingestion warning events', async () => {
            const events = [
                createEvent({
                    event: '$$client_ingestion_warning',
                    properties: {
                        $$client_ingestion_warning_message: 'test warning',
                    },
                }),
            ]
            await ingester.handleKafkaBatch(createKafkaMessages(events))

            const allMessages = mockProducerObserver.getProducedKafkaMessages()
            // Client ingestion warnings produce to the ingestion_warnings topic
            const warningMessages = allMessages.filter((m) => m.topic === 'clickhouse_ingestion_warnings_test')
            expect(warningMessages).toHaveLength(1)
        })
    })

    describe('heatmap subpipeline', () => {
        it('should produce heatmap events to the heatmaps topic', async () => {
            const events = [
                createEvent({
                    event: '$$heatmap',
                    properties: {
                        $viewport_height: 800,
                        $viewport_width: 1200,
                        $session_id: 'session-1',
                        $heatmap_data: {
                            'http://localhost:3000/': [
                                {
                                    x: 1020,
                                    y: 363,
                                    target_fixed: false,
                                    type: 'click',
                                },
                            ],
                        },
                    },
                }),
            ]
            await ingester.handleKafkaBatch(createKafkaMessages(events))

            const allMessages = mockProducerObserver.getProducedKafkaMessages()
            const heatmapMessages = allMessages.filter((m) => m.topic === 'clickhouse_heatmap_events_test')
            expect(heatmapMessages).toHaveLength(1)

            // Should NOT produce to the regular events topic
            const eventMessages = allMessages.filter((m) => m.topic === 'clickhouse_events_json_test')
            expect(eventMessages).toHaveLength(0)
        })

        it('should not produce person messages for heatmap events', async () => {
            const events = [
                createEvent({
                    event: '$$heatmap',
                    properties: {
                        $viewport_height: 800,
                        $viewport_width: 1200,
                        $session_id: 'session-1',
                        $heatmap_data: {
                            'http://localhost:3000/': [{ x: 100, y: 200, target_fixed: false, type: 'click' }],
                        },
                    },
                }),
            ]
            await ingester.handleKafkaBatch(createKafkaMessages(events))

            const allMessages = mockProducerObserver.getProducedKafkaMessages()
            const personMessages = allMessages.filter(
                (m) => m.topic === 'clickhouse_person_test' || m.topic === 'clickhouse_person_distinct_id2_test'
            )
            expect(personMessages).toHaveLength(0)
        })
    })

    describe('AI event subpipeline', () => {
        it('should process $ai_generation events', async () => {
            const events = [
                createEvent({
                    event: '$ai_generation',
                    properties: {
                        $ai_model: 'gpt-4',
                        $ai_provider: 'openai',
                        $ai_input_tokens: 100,
                        $ai_output_tokens: 50,
                        $ai_input: 'What is the meaning of life?',
                        $ai_output: 'The meaning of life is 42.',
                    },
                }),
            ]
            await ingester.handleKafkaBatch(createKafkaMessages(events))

            const eventMessages = mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(eventMessages).toHaveLength(1)
            expect(eventMessages[0].value.event).toBe('$ai_generation')
        })

        it('should not produce person messages for AI events', async () => {
            const events = [
                createEvent({
                    event: '$ai_generation',
                    properties: {
                        $ai_model: 'gpt-4',
                        $ai_provider: 'openai',
                    },
                }),
            ]
            await ingester.handleKafkaBatch(createKafkaMessages(events))

            const allMessages = mockProducerObserver.getProducedKafkaMessages()
            const personMessages = allMessages.filter(
                (m) => m.topic === 'clickhouse_person_test' || m.topic === 'clickhouse_person_distinct_id2_test'
            )
            expect(personMessages).toHaveLength(0)
        })
    })

    describe('all subpipelines in one batch', () => {
        it('should route different event types to their correct subpipelines', async () => {
            const events = [
                createEvent({ event: '$pageview', distinct_id: 'user-1' }),
                createEvent({
                    event: '$$heatmap',
                    distinct_id: 'user-2',
                    properties: {
                        $viewport_height: 800,
                        $viewport_width: 1200,
                        $session_id: 'session-1',
                        $heatmap_data: {
                            'http://localhost:3000/': [{ x: 10, y: 20, target_fixed: false, type: 'click' }],
                        },
                    },
                }),
                createEvent({
                    event: '$ai_generation',
                    distinct_id: 'user-3',
                    properties: {
                        $ai_model: 'gpt-4',
                        $ai_provider: 'openai',
                        $ai_input: 'hello',
                        $ai_output: 'world',
                    },
                }),
                createEvent({
                    event: '$$client_ingestion_warning',
                    distinct_id: 'user-4',
                    properties: { $$client_ingestion_warning_message: 'warning' },
                }),
            ]
            await ingester.handleKafkaBatch(createKafkaMessages(events))

            const allMessages = mockProducerObserver.getProducedKafkaMessages()

            // Regular event + AI event → clickhouse_events_json (no AI splitting in testing pipeline)
            const eventMessages = allMessages.filter((m) => m.topic === 'clickhouse_events_json_test')
            expect(eventMessages).toHaveLength(2) // pageview + ai_generation

            // Heatmap → clickhouse_heatmap_events
            const heatmapMessages = allMessages.filter((m) => m.topic === 'clickhouse_heatmap_events_test')
            expect(heatmapMessages).toHaveLength(1)

            // Client ingestion warning → clickhouse_ingestion_warnings
            const warningMessages = allMessages.filter((m) => m.topic === 'clickhouse_ingestion_warnings_test')
            expect(warningMessages).toHaveLength(1)

            // No person messages from any subpipeline
            const personMessages = allMessages.filter(
                (m) => m.topic === 'clickhouse_person_test' || m.topic === 'clickhouse_person_distinct_id2_test'
            )
            expect(personMessages).toHaveLength(0)
        })
    })
})
