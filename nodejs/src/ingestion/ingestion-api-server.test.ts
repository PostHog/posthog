import { MessageHeader } from 'node-rdkafka'

import { parseJSON } from '../utils/json-parse'
import { serializeKafkaMessage } from './api/kafka-message-converter'
import { IngestBatchRequest, IngestBatchResponse, SerializedKafkaMessage } from './api/types'

function makeHeader(key: string, value: Buffer): MessageHeader {
    const h: MessageHeader = {}
    h[key] = value
    return h
}

function makeSerializedMessage(overrides: Partial<SerializedKafkaMessage> = {}): SerializedKafkaMessage {
    const eventBody = JSON.stringify({
        event: '$pageview',
        properties: { $current_url: 'https://example.com' },
    })
    return {
        topic: 'events_plugin_ingestion',
        partition: 0,
        offset: 0,
        key: Buffer.from('phc_abc:user-1').toString('base64'),
        value: Buffer.from(eventBody).toString('base64'),
        headers: [
            { token: Buffer.from('phc_abc').toString('base64') },
            { distinct_id: Buffer.from('user-1').toString('base64') },
        ],
        ...overrides,
    }
}

describe('ingestion-api-server', () => {
    describe('request validation', () => {
        it('serialized message matches expected JSON schema', () => {
            const msg = serializeKafkaMessage({
                topic: 'events_plugin_ingestion',
                partition: 3,
                offset: 12345,
                timestamp: 1708012800000,
                size: 0,
                key: Buffer.from('phc_abc:user-1'),
                value: Buffer.from('{"event":"$pageview"}'),
                headers: [
                    makeHeader('token', Buffer.from('phc_abc')),
                    makeHeader('distinct_id', Buffer.from('user-1')),
                ],
            })

            expect(msg).toMatchObject({
                topic: 'events_plugin_ingestion',
                partition: 3,
                offset: 12345,
                timestamp: 1708012800000,
            })
            expect(typeof msg.key).toBe('string')
            expect(typeof msg.value).toBe('string')
            expect(msg.headers).toHaveLength(2)
            expect(typeof msg.headers[0]['token']).toBe('string')
        })

        it('IngestBatchRequest can be JSON serialized and parsed', () => {
            const request: IngestBatchRequest = {
                messages: [makeSerializedMessage(), makeSerializedMessage({ partition: 1, offset: 1 })],
            }

            const json = JSON.stringify(request)
            const parsed = parseJSON(json) as IngestBatchRequest

            expect(parsed.messages).toHaveLength(2)
            expect(parsed.messages[0].topic).toBe('events_plugin_ingestion')
            expect(parsed.messages[1].partition).toBe(1)
        })

        it('IngestBatchResponse ok format', () => {
            const response: IngestBatchResponse = { status: 'ok', accepted: 5 }
            expect(parseJSON(JSON.stringify(response))).toEqual({ status: 'ok', accepted: 5 })
        })

        it('IngestBatchResponse error format', () => {
            const response: IngestBatchResponse = { status: 'error', error: 'pipeline failed' }
            expect(parseJSON(JSON.stringify(response))).toEqual({ status: 'error', error: 'pipeline failed' })
        })

        it('empty messages array is valid', () => {
            const request: IngestBatchRequest = { messages: [] }
            expect(request.messages).toHaveLength(0)
        })
    })
})
