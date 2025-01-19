import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { UUIDT } from '~/src/utils/utils'
import { getParsedQueuedMessages, mockProducer } from '~/tests/helpers/mocks/producer.mock'

import { Hub, PipelineEvent, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { IngestionConsumer } from './ingestion-consumer'

const mockConsumer = {
    on: jest.fn(),
    commitSync: jest.fn(),
    commit: jest.fn(),
    queryWatermarkOffsets: jest.fn(),
    committed: jest.fn(),
    assignments: jest.fn(),
    isConnected: jest.fn(() => true),
    getMetadata: jest.fn(),
}

jest.mock('../../src/kafka/batch-consumer', () => {
    return {
        startBatchConsumer: jest.fn(() =>
            Promise.resolve({
                join: () => ({
                    finally: jest.fn(),
                }),
                stop: jest.fn(),
                consumer: mockConsumer,
            })
        ),
    }
})

jest.setTimeout(1000)

type DecodedKafkaMessage = {
    topic: string
    key?: any
    value: Record<string, unknown>
}

const decodeAllKafkaMessages = (): DecodedKafkaMessage[] => {
    const queuedMessages = getParsedQueuedMessages()

    const result: DecodedKafkaMessage[] = []

    for (const topicMessage of queuedMessages) {
        for (const message of topicMessage.messages) {
            result.push({
                topic: topicMessage.topic,
                key: message.key,
                value: message.value ?? {},
            })
        }
    }

    return result
}

let offsetIncrementer = 0

const createKafkaMessages: (events: PipelineEvent[]) => Message[] = (events) => {
    return events.map((event) => {
        // TRICKY: This is the slightly different format that capture sends
        const captureEvent = {
            uuid: event.uuid,
            distinct_id: event.distinct_id,
            ip: event.ip,
            now: event.now,
            token: event.token,
            data: JSON.stringify(event),
        }
        return {
            value: Buffer.from(JSON.stringify(captureEvent)),
            size: 1,
            topic: 'test',
            offset: offsetIncrementer++,
            partition: 1,
        }
    })
}

describe('IngestionConsumer', () => {
    let ingester: IngestionConsumer
    let hub: Hub
    let team: Team

    const createEvent = (event?: Partial<PipelineEvent>): PipelineEvent => ({
        distinct_id: 'user-1',
        uuid: new UUIDT().toString(),
        token: team.api_token,
        ip: '127.0.0.1',
        site_url: 'us.posthog.com',
        now: DateTime.now().toISO(),
        event: '$pageview',
        properties: {
            $current_url: 'http://localhost:8000',
        },
        ...event,
    })

    beforeEach(async () => {
        offsetIncrementer = 0
        await resetTestDatabase()
        hub = await createHub()
        hub.kafkaProducer = mockProducer
        team = await getFirstTeam(hub)

        ingester = new IngestionConsumer(hub)
        await ingester.start()
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await ingester.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('general', () => {
        beforeEach(async () => {})

        it('should process events', async () => {
            const messages = createKafkaMessages([createEvent()])
            await ingester.handleKafkaBatch(messages)

            expect(decodeAllKafkaMessages()).toMatchInlineSnapshot(`
                [
                  {
                    "key": null,
                    "topic": "clickhouse_person_test",
                    "value": {
                      "created_at": "2025-01-19 11:42:38",
                      "id": "1e7731c8-945c-520d-96b9-e7f088242010",
                      "is_deleted": 0,
                      "is_identified": 0,
                      "properties": "{"$current_url":"http://localhost:8000","$creator_event_uuid":"01947e5f-3be8-0000-0507-06a17ba519e0","$initial_current_url":"http://localhost:8000"}",
                      "team_id": 2,
                      "version": 0,
                    },
                  },
                  {
                    "key": null,
                    "topic": "clickhouse_person_distinct_id_test",
                    "value": {
                      "distinct_id": "user-1",
                      "is_deleted": 0,
                      "person_id": "1e7731c8-945c-520d-96b9-e7f088242010",
                      "team_id": 2,
                      "version": 0,
                    },
                  },
                  {
                    "key": null,
                    "topic": "events_dead_letter_queue_test",
                    "value": {
                      "distinct_id": "user-1",
                      "error": "Event ingestion failed. Error: Cannot read properties of undefined (reading 'catch')",
                      "error_location": "plugin_server_ingest_event:emitEventStep",
                      "error_timestamp": "2025-01-19 11:42:38",
                      "event": "$pageview",
                      "event_uuid": "01947e5f-3be8-0000-0507-06a17ba519e0",
                      "id": "01947e5f-3c08-0000-2bf7-132f2d57fae8",
                      "ip": "",
                      "now": "2025-01-19 11:42:38",
                      "properties": "{"$current_url":"http://localhost:8000","$ip":"127.0.0.1","$set":{"$current_url":"http://localhost:8000"},"$set_once":{"$initial_current_url":"http://localhost:8000"}}",
                      "raw_payload": "{"distinct_id":"user-1","uuid":"01947e5f-3be8-0000-0507-06a17ba519e0","token":"THIS IS NOT A TOKEN FOR TEAM 2","ip":null,"site_url":"us.posthog.com","now":"2025-01-19T12:42:38.056+01:00","event":"$pageview","properties":{"$current_url":"http://localhost:8000","$ip":"127.0.0.1","$set":{"$current_url":"http://localhost:8000"},"$set_once":{"$initial_current_url":"http://localhost:8000"}}}",
                      "site_url": "us.posthog.com",
                      "tags": [
                        "plugin_server",
                        "ingest_event",
                      ],
                      "team_id": 2,
                      "token": "THIS IS NOT A TOKEN FOR TEAM 2",
                      "uuid": "01947e5f-3be8-0000-0507-06a17ba519e0",
                    },
                  },
                ]
            `)
        })
    })
})
