import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { KafkaMessageParser } from '../../session-recording/kafka/message-parser'
import { ParsedMessageData } from '../../session-recording/kafka/types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '../event-preprocessing'
import { drop, ok, redirect } from '../pipelines/results'
import { createSessionReplayPipeline, runSessionReplayPipeline } from './session-replay-pipeline'

jest.mock('../event-preprocessing', () => ({
    createParseHeadersStep: jest.fn(),
    createApplyEventRestrictionsStep: jest.fn(),
}))

const mockCreateParseHeadersStep = createParseHeadersStep as jest.Mock
const mockCreateApplyEventRestrictionsStep = createApplyEventRestrictionsStep as jest.Mock

describe('session-replay-pipeline', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let mockParser: jest.Mocked<KafkaMessageParser>
    let mockRestrictionManager: any
    let promiseScheduler: PromiseScheduler

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

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
            disconnect: jest.fn().mockResolvedValue(undefined),
        } as any

        mockParser = {
            parseMessage: jest
                .fn()
                .mockImplementation((msg: Message) => Promise.resolve(createParsedMessage(msg.offset))),
        } as any

        mockRestrictionManager = {}

        promiseScheduler = new PromiseScheduler()

        // Default: parse headers step passes through with parsed headers
        // Kafka headers are an array of { [key]: Buffer } objects
        mockCreateParseHeadersStep.mockReturnValue((input: any) => {
            const headers: Record<string, string> = {}
            for (const header of input.message.headers || []) {
                for (const [key, value] of Object.entries(header)) {
                    headers[key] = (value as Buffer).toString()
                }
            }
            return Promise.resolve(ok({ ...input, headers }))
        })

        // Default: restrictions step passes through
        mockCreateApplyEventRestrictionsStep.mockReturnValue((input: any) => {
            return Promise.resolve(ok(input))
        })
    })

    function createMessage(partition: number, offset: number, headers?: Record<string, string>): Message {
        const kafkaHeaders = headers
            ? Object.entries(headers).map(([key, value]) => ({ [key]: Buffer.from(value) }))
            : []

        return {
            partition,
            offset,
            topic: 'test-topic',
            value: Buffer.from('test-value'),
            key: Buffer.from('test-key'),
            timestamp: Date.now(),
            headers: kafkaHeaders,
            size: 100,
        }
    }

    describe('runSessionReplayPipeline', () => {
        it('passes through messages when no restrictions apply', async () => {
            const pipeline = createSessionReplayPipeline({
                parser: mockParser,
                kafkaProducer: mockKafkaProducer,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
            })

            const messages = [createMessage(0, 1), createMessage(0, 2)]

            const result = await runSessionReplayPipeline(pipeline, messages)

            expect(result).toHaveLength(2)
            expect(result[0].session_id).toBe('session-1')
            expect(result[1].session_id).toBe('session-2')
        })

        it('filters out dropped messages from restrictions', async () => {
            mockCreateApplyEventRestrictionsStep.mockReturnValue((input: any) => {
                if (input.message.offset === 2) {
                    return Promise.resolve(drop('blocked'))
                }
                return Promise.resolve(ok(input))
            })

            const pipeline = createSessionReplayPipeline({
                parser: mockParser,
                kafkaProducer: mockKafkaProducer,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
            })

            const messages = [createMessage(0, 1), createMessage(0, 2), createMessage(0, 3)]

            const result = await runSessionReplayPipeline(pipeline, messages)

            expect(result).toHaveLength(2)
            expect(result[0].session_id).toBe('session-1')
            expect(result[1].session_id).toBe('session-3')
        })

        it('filters out messages that fail to parse', async () => {
            mockParser.parseMessage.mockImplementation((msg: Message) => {
                if (msg.offset === 2) {
                    return Promise.resolve(null)
                }
                return Promise.resolve(createParsedMessage(msg.offset))
            })

            const pipeline = createSessionReplayPipeline({
                parser: mockParser,
                kafkaProducer: mockKafkaProducer,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
            })

            const messages = [createMessage(0, 1), createMessage(0, 2), createMessage(0, 3)]

            const result = await runSessionReplayPipeline(pipeline, messages)

            expect(result).toHaveLength(2)
            expect(result[0].session_id).toBe('session-1')
            expect(result[1].session_id).toBe('session-3')
        })

        it('redirects overflow messages and filters them out', async () => {
            mockCreateApplyEventRestrictionsStep.mockReturnValue((input: any) => {
                if (input.message.offset === 2) {
                    return Promise.resolve(redirect('overflow', 'overflow-topic', true, false))
                }
                return Promise.resolve(ok(input))
            })

            const pipeline = createSessionReplayPipeline({
                parser: mockParser,
                kafkaProducer: mockKafkaProducer,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
            })

            const messages = [createMessage(0, 1), createMessage(0, 2), createMessage(0, 3)]

            const result = await runSessionReplayPipeline(pipeline, messages)

            // Wait for side effects to complete
            await promiseScheduler.waitForAll()

            expect(result).toHaveLength(2)
            expect(result[0].session_id).toBe('session-1')
            expect(result[1].session_id).toBe('session-3')

            // Verify the overflow message was produced
            expect(mockKafkaProducer.produce).toHaveBeenCalledWith(
                expect.objectContaining({
                    topic: 'overflow-topic',
                })
            )
        })

        it('returns empty array for empty input', async () => {
            const pipeline = createSessionReplayPipeline({
                parser: mockParser,
                kafkaProducer: mockKafkaProducer,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
            })

            const result = await runSessionReplayPipeline(pipeline, [])

            expect(result).toHaveLength(0)
        })

        it('processes large batch with mixed dropped and passed messages correctly', async () => {
            // Drop every 10th message via restrictions
            mockCreateApplyEventRestrictionsStep.mockReturnValue((input: any) => {
                if (input.message.offset % 10 === 0) {
                    return Promise.resolve(drop('blocked'))
                }
                return Promise.resolve(ok(input))
            })

            const pipeline = createSessionReplayPipeline({
                parser: mockParser,
                kafkaProducer: mockKafkaProducer,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
            })

            // Create 1000 messages
            const messages: Message[] = []
            for (let i = 1; i <= 1000; i++) {
                messages.push(createMessage(0, i))
            }

            const result = await runSessionReplayPipeline(pipeline, messages)

            // 100 messages should be dropped (10, 20, 30, ..., 1000)
            // 900 messages should pass through
            expect(result).toHaveLength(900)

            // Verify the session_ids are correct (all non-multiples of 10)
            const resultSessionIds = result.map((m) => m.session_id)
            for (let i = 1; i <= 1000; i++) {
                if (i % 10 === 0) {
                    expect(resultSessionIds).not.toContain(`session-${i}`)
                } else {
                    expect(resultSessionIds).toContain(`session-${i}`)
                }
            }
        })

        it('correctly parses and passes headers to the restrictions step', async () => {
            // Track what headers are passed to the restrictions step
            const capturedHeaders: Record<string, string>[] = []
            mockCreateApplyEventRestrictionsStep.mockReturnValue((input: any) => {
                capturedHeaders.push(input.headers)
                return Promise.resolve(ok(input))
            })

            const pipeline = createSessionReplayPipeline({
                parser: mockParser,
                kafkaProducer: mockKafkaProducer,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
            })

            const messages = [
                createMessage(0, 1, { token: 'team-token-123', distinctId: 'user-456' }),
                createMessage(0, 2, { token: 'team-token-789' }),
            ]

            const result = await runSessionReplayPipeline(pipeline, messages)

            expect(result).toHaveLength(2)
            // Verify headers were correctly parsed and passed through
            expect(capturedHeaders).toHaveLength(2)
            expect(capturedHeaders[0]).toEqual({ token: 'team-token-123', distinctId: 'user-456' })
            expect(capturedHeaders[1]).toEqual({ token: 'team-token-789' })
        })

        it('processes large batch with all messages passing through', async () => {
            const pipeline = createSessionReplayPipeline({
                parser: mockParser,
                kafkaProducer: mockKafkaProducer,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
            })

            // Create 500 messages
            const messages: Message[] = []
            for (let i = 1; i <= 500; i++) {
                messages.push(createMessage(0, i))
            }

            const result = await runSessionReplayPipeline(pipeline, messages)

            expect(result).toHaveLength(500)

            // Verify all session_ids are present and in order
            for (let i = 0; i < 500; i++) {
                expect(result[i].session_id).toBe(`session-${i + 1}`)
            }
        })

        it('handles messages with no headers', async () => {
            const capturedHeaders: Record<string, string>[] = []
            mockCreateApplyEventRestrictionsStep.mockReturnValue((input: any) => {
                capturedHeaders.push(input.headers)
                return Promise.resolve(ok(input))
            })

            const pipeline = createSessionReplayPipeline({
                parser: mockParser,
                kafkaProducer: mockKafkaProducer,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
            })

            const messages = [createMessage(0, 1)] // No headers

            const result = await runSessionReplayPipeline(pipeline, messages)

            expect(result).toHaveLength(1)
            expect(capturedHeaders).toHaveLength(1)
            expect(capturedHeaders[0]).toEqual({})
        })
    })
})
