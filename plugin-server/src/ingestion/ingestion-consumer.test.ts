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

const UUID_REGEX = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi
const forSnapshot = (obj: any, idMap?: Record<string, string>) => {
    idMap = idMap ?? {}

    // To make snapshot testing way simpler this matches on UUIDs and replaces them with an incrementing ID

    let strData = JSON.stringify(obj)

    const matches = strData.match(UUID_REGEX)

    for (const match of matches ?? []) {
        idMap[match] = `<REPLACED-UUID-${Object.keys(idMap).length}>`
        strData = strData.replace(match, idMap[match])
    }

    return JSON.parse(strData)
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
        beforeEach(() => {
            // TODO: Freeze time for tests
            // TODO: Add helper to replace all UUIDs with simple strings for better test comaprisons
        })

        it('should process events', async () => {
            const messages = createKafkaMessages([createEvent()])
            await ingester.handleKafkaBatch(messages)

            expect(forSnapshot(decodeAllKafkaMessages())).toMatchSnapshot()
        })
    })
})
