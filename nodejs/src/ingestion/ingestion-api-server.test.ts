import { IngestBatchRequest, IngestBatchResponse, ProtoKafkaMessage } from './api/types'

function makeProtoMessage(overrides: Partial<ProtoKafkaMessage> = {}): ProtoKafkaMessage {
    const eventBody = JSON.stringify({
        event: '$pageview',
        properties: { $current_url: 'https://example.com' },
    })
    return {
        topic: 'events_plugin_ingestion',
        partition: 0,
        offset: 0,
        key: Buffer.from('phc_abc:user-1'),
        value: Buffer.from(eventBody),
        headers: [
            { key: 'token', value: Buffer.from('phc_abc') },
            { key: 'distinct_id', value: Buffer.from('user-1') },
        ],
        ...overrides,
    }
}

describe('ingestion-api-server', () => {
    describe('proto message types', () => {
        it('proto message has raw Buffer key and value', () => {
            const msg = makeProtoMessage()

            expect(Buffer.isBuffer(msg.key)).toBe(true)
            expect(Buffer.isBuffer(msg.value)).toBe(true)
            expect(msg.headers).toHaveLength(2)
            expect(Buffer.isBuffer(msg.headers[0].value)).toBe(true)
        })

        it('IngestBatchRequest holds proto messages', () => {
            const request: IngestBatchRequest = {
                messages: [makeProtoMessage(), makeProtoMessage({ partition: 1, offset: 1 })],
            }

            expect(request.messages).toHaveLength(2)
            expect(request.messages[0].topic).toBe('events_plugin_ingestion')
            expect(request.messages[1].partition).toBe(1)
        })

        it('IngestBatchResponse ok format', () => {
            const response: IngestBatchResponse = { status: 0, accepted: 5, error: '' }
            expect(response.status).toBe(0)
            expect(response.accepted).toBe(5)
        })

        it('IngestBatchResponse error format', () => {
            const response: IngestBatchResponse = { status: 1, accepted: 0, error: 'pipeline failed' }
            expect(response.status).toBe(1)
            expect(response.error).toBe('pipeline failed')
        })

        it('empty messages array is valid', () => {
            const request: IngestBatchRequest = { messages: [] }
            expect(request.messages).toHaveLength(0)
        })
    })
})
