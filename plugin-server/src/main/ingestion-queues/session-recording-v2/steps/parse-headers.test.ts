import { MessageHeader } from 'node-rdkafka'

import { isOkResult } from '../../../../ingestion/pipelines/results'
import { createTestMessage } from '../test-helpers'
import { createParseHeadersStep } from './parse-headers'

describe('parse-headers', () => {
    it('should parse token header', async () => {
        const step = createParseHeadersStep()
        const headers: MessageHeader[] = [{ token: Buffer.from('test-token') }]
        const message = createTestMessage({ headers })

        const result = await step({ message })

        expect(isOkResult(result)).toBe(true)
        expect(result).toMatchObject({
            type: 0, // PipelineResultType.OK
            value: {
                message,
                headers: {
                    token: 'test-token',
                    force_disable_person_processing: false,
                },
            },
        })
    })

    it('should parse distinct_id header', async () => {
        const step = createParseHeadersStep()
        const headers: MessageHeader[] = [{ distinct_id: Buffer.from('user-123') }]
        const message = createTestMessage({ headers })

        const result = await step({ message })

        expect(isOkResult(result)).toBe(true)
        expect(result).toMatchObject({
            type: 0,
            value: {
                message,
                headers: {
                    distinct_id: 'user-123',
                    force_disable_person_processing: false,
                },
            },
        })
    })

    it('should parse multiple headers', async () => {
        const step = createParseHeadersStep()
        const headers: MessageHeader[] = [
            { token: Buffer.from('test-token') },
            { distinct_id: Buffer.from('user-123') },
            { timestamp: Buffer.from('2023-01-01') },
            { event: Buffer.from('$pageview') },
            { uuid: Buffer.from('uuid-123') },
        ]
        const message = createTestMessage({ headers })

        const result = await step({ message })

        expect(isOkResult(result)).toBe(true)
        expect(result).toMatchObject({
            type: 0,
            value: {
                message,
                headers: {
                    token: 'test-token',
                    distinct_id: 'user-123',
                    timestamp: '2023-01-01',
                    event: '$pageview',
                    uuid: 'uuid-123',
                    force_disable_person_processing: false,
                },
            },
        })
    })

    it('should parse force_disable_person_processing as true', async () => {
        const step = createParseHeadersStep()
        const headers: MessageHeader[] = [{ force_disable_person_processing: Buffer.from('true') }]
        const message = createTestMessage({ headers })

        const result = await step({ message })

        expect(isOkResult(result)).toBe(true)
        expect(result).toMatchObject({
            type: 0,
            value: {
                message,
                headers: {
                    force_disable_person_processing: true,
                },
            },
        })
    })

    it('should parse force_disable_person_processing as false', async () => {
        const step = createParseHeadersStep()
        const headers: MessageHeader[] = [{ force_disable_person_processing: Buffer.from('false') }]
        const message = createTestMessage({ headers })

        const result = await step({ message })

        expect(isOkResult(result)).toBe(true)
        expect(result).toMatchObject({
            type: 0,
            value: {
                message,
                headers: {
                    force_disable_person_processing: false,
                },
            },
        })
    })

    it('should handle empty headers', async () => {
        const step = createParseHeadersStep()
        const message = createTestMessage({ headers: [] })

        const result = await step({ message })

        expect(isOkResult(result)).toBe(true)
        expect(result).toMatchObject({
            type: 0,
            value: {
                message,
                headers: {
                    force_disable_person_processing: false,
                },
            },
        })
    })

    it('should handle undefined headers', async () => {
        const step = createParseHeadersStep()
        const message = createTestMessage({ headers: undefined })

        const result = await step({ message })

        expect(isOkResult(result)).toBe(true)
        expect(result).toMatchObject({
            type: 0,
            value: {
                message,
                headers: {
                    force_disable_person_processing: false,
                },
            },
        })
    })

    it('should return original message along with headers', async () => {
        const step = createParseHeadersStep()
        const headers: MessageHeader[] = [{ token: Buffer.from('test-token') }]
        const message = createTestMessage({ headers, partition: 5, offset: 100 })

        const result = await step({ message })

        expect(isOkResult(result)).toBe(true)
        expect(result).toMatchObject({
            type: 0,
            value: {
                message,
                headers: {
                    token: 'test-token',
                    force_disable_person_processing: false,
                },
            },
        })
    })
})
