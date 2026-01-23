import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '../event-preprocessing'
import { drop, ok, redirect } from '../pipelines/results'
import { applyRestrictions, createRestrictionPipeline } from './restriction-pipeline'

jest.mock('../event-preprocessing', () => ({
    createParseHeadersStep: jest.fn(),
    createApplyEventRestrictionsStep: jest.fn(),
}))

const mockCreateParseHeadersStep = createParseHeadersStep as jest.Mock
const mockCreateApplyEventRestrictionsStep = createApplyEventRestrictionsStep as jest.Mock

describe('restriction-pipeline', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let mockRestrictionManager: any
    let promiseScheduler: PromiseScheduler

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
            disconnect: jest.fn().mockResolvedValue(undefined),
        } as any

        mockRestrictionManager = {}

        promiseScheduler = new PromiseScheduler()

        // Default: parse headers step passes through with parsed headers
        mockCreateParseHeadersStep.mockReturnValue((input: any) => {
            return Promise.resolve(ok({ ...input, headers: { token: input.message.headers?.[0]?.token?.toString() } }))
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

    describe('applyRestrictions', () => {
        it('passes through messages when no restrictions apply', async () => {
            const pipeline = createRestrictionPipeline({
                kafkaProducer: mockKafkaProducer,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
            })

            const messages = [createMessage(0, 1), createMessage(0, 2)]

            const result = await applyRestrictions(pipeline, messages)

            expect(result).toHaveLength(2)
            expect(result[0].offset).toBe(1)
            expect(result[1].offset).toBe(2)
        })

        it('filters out dropped messages', async () => {
            mockCreateApplyEventRestrictionsStep.mockReturnValue((input: any) => {
                if (input.message.offset === 2) {
                    return Promise.resolve(drop('blocked'))
                }
                return Promise.resolve(ok(input))
            })

            const pipeline = createRestrictionPipeline({
                kafkaProducer: mockKafkaProducer,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
            })

            const messages = [createMessage(0, 1), createMessage(0, 2), createMessage(0, 3)]

            const result = await applyRestrictions(pipeline, messages)

            expect(result).toHaveLength(2)
            expect(result[0].offset).toBe(1)
            expect(result[1].offset).toBe(3)
        })

        it('redirects overflow messages and filters them out', async () => {
            mockCreateApplyEventRestrictionsStep.mockReturnValue((input: any) => {
                if (input.message.offset === 2) {
                    return Promise.resolve(redirect('overflow', 'overflow-topic', true, false))
                }
                return Promise.resolve(ok(input))
            })

            const pipeline = createRestrictionPipeline({
                kafkaProducer: mockKafkaProducer,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
            })

            const messages = [createMessage(0, 1), createMessage(0, 2), createMessage(0, 3)]

            const result = await applyRestrictions(pipeline, messages)

            // Wait for side effects to complete
            await promiseScheduler.waitForAll()

            expect(result).toHaveLength(2)
            expect(result[0].offset).toBe(1)
            expect(result[1].offset).toBe(3)

            // Verify the overflow message was produced
            expect(mockKafkaProducer.produce).toHaveBeenCalledWith(
                expect.objectContaining({
                    topic: 'overflow-topic',
                })
            )
        })

        it('returns empty array for empty input', async () => {
            const pipeline = createRestrictionPipeline({
                kafkaProducer: mockKafkaProducer,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
            })

            const result = await applyRestrictions(pipeline, [])

            expect(result).toHaveLength(0)
        })

        it('processes large batch with mixed dropped and passed messages correctly', async () => {
            // Drop every 10th message
            mockCreateApplyEventRestrictionsStep.mockReturnValue((input: any) => {
                if (input.message.offset % 10 === 0) {
                    return Promise.resolve(drop('blocked'))
                }
                return Promise.resolve(ok(input))
            })

            const pipeline = createRestrictionPipeline({
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

            const result = await applyRestrictions(pipeline, messages)

            // 100 messages should be dropped (10, 20, 30, ..., 1000)
            // 900 messages should pass through
            expect(result).toHaveLength(900)

            // Verify the offsets are correct (all non-multiples of 10)
            const resultOffsets = result.map((m) => m.offset)
            for (let i = 1; i <= 1000; i++) {
                if (i % 10 === 0) {
                    expect(resultOffsets).not.toContain(i)
                } else {
                    expect(resultOffsets).toContain(i)
                }
            }
        })

        it('processes large batch with all messages passing through', async () => {
            const pipeline = createRestrictionPipeline({
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

            const result = await applyRestrictions(pipeline, messages)

            expect(result).toHaveLength(500)

            // Verify all offsets are present and in order
            for (let i = 0; i < 500; i++) {
                expect(result[i].offset).toBe(i + 1)
            }
        })
    })
})
