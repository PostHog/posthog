import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { KafkaMessageParser } from '../../session-recording/kafka/message-parser'
import { ParsedMessageData } from '../../session-recording/kafka/types'
import { PipelineResultType } from '../pipelines/results'
import { ParseMessageStepInput, createParseMessageStep } from './parse-message-step'

describe('createParseMessageStep', () => {
    const createMessage = (partition: number, offset: number): Message => ({
        partition,
        offset,
        topic: 'test-topic',
        value: Buffer.from('test-value'),
        key: Buffer.from('test-key'),
        timestamp: Date.now(),
        headers: [],
        size: 100,
    })

    const createInput = (partition: number, offset: number): ParseMessageStepInput => ({
        message: createMessage(partition, offset),
    })

    const createParsedMessage = (offset: number): ParsedMessageData => ({
        metadata: {
            partition: 0,
            topic: 'test-topic',
            offset,
            timestamp: 1234567890,
            rawSize: 100,
        },
        headers: [],
        distinct_id: 'distinct_id',
        session_id: `session-${offset}`,
        token: 'test-token',
        eventsByWindowId: { window1: [] },
        eventsRange: { start: DateTime.fromMillis(0), end: DateTime.fromMillis(0) },
        snapshot_source: null,
        snapshot_library: null,
    })

    it('should parse valid messages and return ok results', async () => {
        const mockParser = {
            parseMessage: jest
                .fn()
                .mockImplementation((msg: Message) => Promise.resolve(createParsedMessage(msg.offset))),
        } as unknown as KafkaMessageParser

        const step = createParseMessageStep(mockParser)
        const inputs = [createInput(0, 1), createInput(0, 2)]

        const results = await step(inputs)

        expect(results).toHaveLength(2)
        expect(results[0].type).toBe(PipelineResultType.OK)
        expect(results[1].type).toBe(PipelineResultType.OK)

        if (results[0].type === PipelineResultType.OK) {
            expect(results[0].value.session_id).toBe('session-1')
        }
        if (results[1].type === PipelineResultType.OK) {
            expect(results[1].value.session_id).toBe('session-2')
        }
    })

    it('should drop messages that fail to parse', async () => {
        const mockParser = {
            parseMessage: jest.fn().mockImplementation((msg: Message) => {
                if (msg.offset === 2) {
                    return Promise.resolve(null)
                }
                return Promise.resolve(createParsedMessage(msg.offset))
            }),
        } as unknown as KafkaMessageParser

        const step = createParseMessageStep(mockParser)
        const inputs = [createInput(0, 1), createInput(0, 2), createInput(0, 3)]

        const results = await step(inputs)

        expect(results).toHaveLength(3)
        expect(results[0].type).toBe(PipelineResultType.OK)
        expect(results[1].type).toBe(PipelineResultType.DROP)
        expect(results[2].type).toBe(PipelineResultType.OK)

        if (results[1].type === PipelineResultType.DROP) {
            expect(results[1].reason).toBe('invalid_message')
        }
    })

    it('should handle empty batch', async () => {
        const mockParser = {
            parseMessage: jest.fn(),
        } as unknown as KafkaMessageParser

        const step = createParseMessageStep(mockParser)
        const results = await step([])

        expect(results).toHaveLength(0)
        expect(mockParser.parseMessage).not.toHaveBeenCalled()
    })

    it('should call parser for each message', async () => {
        const mockParser = {
            parseMessage: jest.fn().mockResolvedValue(createParsedMessage(1)),
        } as unknown as KafkaMessageParser

        const step = createParseMessageStep(mockParser)
        const inputs = [createInput(0, 1), createInput(0, 2), createInput(0, 3)]

        await step(inputs)

        expect(mockParser.parseMessage).toHaveBeenCalledTimes(3)
        expect(mockParser.parseMessage).toHaveBeenCalledWith(inputs[0].message)
        expect(mockParser.parseMessage).toHaveBeenCalledWith(inputs[1].message)
        expect(mockParser.parseMessage).toHaveBeenCalledWith(inputs[2].message)
    })

    it('should extract message from input with additional properties', async () => {
        const mockParser = {
            parseMessage: jest.fn().mockResolvedValue(createParsedMessage(1)),
        } as unknown as KafkaMessageParser

        const step = createParseMessageStep(mockParser)
        // Simulate restriction pipeline output which has message + headers
        const inputWithExtras = {
            message: createMessage(0, 1),
            headers: { token: 'test-token' },
        }

        const results = await step([inputWithExtras])

        expect(results).toHaveLength(1)
        expect(results[0].type).toBe(PipelineResultType.OK)
        expect(mockParser.parseMessage).toHaveBeenCalledWith(inputWithExtras.message)
    })
})
