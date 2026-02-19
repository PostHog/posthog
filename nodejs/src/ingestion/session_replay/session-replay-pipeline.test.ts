import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { TeamForReplay } from '../../session-recording/teams/types'
import { TeamService } from '../../session-replay/shared/teams/team-service'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
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

type MockKafkaProducer = Pick<KafkaProducerWrapper, 'produce' | 'flush' | 'disconnect'>

describe('session-replay-pipeline', () => {
    let mockKafkaProducer: jest.Mocked<MockKafkaProducer>
    let mockRestrictionManager: EventIngestionRestrictionManager
    let mockTeamService: TeamService
    let promiseScheduler: PromiseScheduler

    const defaultTeam: TeamForReplay = {
        teamId: 1,
        consoleLogIngestionEnabled: false,
    }

    const now = DateTime.now()

    function createValidSnapshotPayload(sessionId: string, windowId = 'window-1'): string {
        const event = {
            event: '$snapshot_items',
            properties: {
                $session_id: sessionId,
                $window_id: windowId,
                $snapshot_items: [
                    { type: 2, timestamp: now.toMillis(), data: {} },
                    { type: 3, timestamp: now.plus({ seconds: 1 }).toMillis(), data: {} },
                ],
            },
        }
        const rawMessage = {
            distinct_id: 'user-123',
            data: JSON.stringify(event),
        }
        return JSON.stringify(rawMessage)
    }

    beforeEach(() => {
        jest.clearAllMocks()

        mockKafkaProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
            disconnect: jest.fn().mockResolvedValue(undefined),
        }

        // The restriction manager is not actually used since we mock createApplyEventRestrictionsStep
        mockRestrictionManager = {} as unknown as EventIngestionRestrictionManager

        // Default: team service validates all messages
        mockTeamService = {
            getTeamByToken: jest.fn().mockResolvedValue(defaultTeam),
            getRetentionPeriodByTeamId: jest.fn().mockResolvedValue(30),
        } as unknown as TeamService

        promiseScheduler = new PromiseScheduler()

        // Default: parse headers step passes through with parsed headers
        // Kafka headers are an array of { [key]: Buffer } objects
        mockCreateParseHeadersStep.mockReturnValue((input: { message: Message; headers?: Record<string, string> }) => {
            const headers: Record<string, string> = {}
            for (const header of input.message.headers || []) {
                for (const [key, value] of Object.entries(header)) {
                    headers[key] = Buffer.isBuffer(value) ? value.toString() : value
                }
            }
            return Promise.resolve(ok({ ...input, headers }))
        })

        // Default: restrictions step passes through
        mockCreateApplyEventRestrictionsStep.mockReturnValue(
            (input: { message: Message; headers: Record<string, string> }) => {
                return Promise.resolve(ok(input))
            }
        )
    })

    function createMessage(
        partition: number,
        offset: number,
        sessionId?: string,
        headers?: Record<string, string>
    ): Message {
        // Default to including a token header since team filtering requires it
        const headersWithDefaults = headers ?? { token: 'test-token' }
        const kafkaHeaders = Object.entries(headersWithDefaults).map(([key, value]) => ({
            [key]: Buffer.from(value),
        }))

        const payload = sessionId
            ? createValidSnapshotPayload(sessionId)
            : createValidSnapshotPayload(`session-${offset}`)

        return {
            partition,
            offset,
            topic: 'test-topic',
            value: Buffer.from(payload),
            key: Buffer.from('test-key'),
            timestamp: Date.now(),
            headers: kafkaHeaders,
            size: payload.length,
        }
    }

    describe('runSessionReplayPipeline', () => {
        it('passes through messages when no restrictions apply', async () => {
            const pipeline = createSessionReplayPipeline({
                kafkaProducer: mockKafkaProducer as unknown as KafkaProducerWrapper,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                dlqTopic: 'dlq-topic',
                promiseScheduler,
                teamService: mockTeamService,
            })

            const messages = [createMessage(0, 1, 'session-1'), createMessage(0, 2, 'session-2')]

            const result = await runSessionReplayPipeline(pipeline, messages)

            expect(result).toHaveLength(2)
            expect(result[0].parsedMessage.session_id).toBe('session-1')
            expect(result[0].team.teamId).toBe(1)
            expect(result[1].parsedMessage.session_id).toBe('session-2')
            expect(result[1].team.teamId).toBe(1)
        })

        it('filters out dropped messages from restrictions', async () => {
            mockCreateApplyEventRestrictionsStep.mockReturnValue(
                (input: { message: Message; headers: Record<string, string> }) => {
                    if (input.message.offset === 2) {
                        return Promise.resolve(drop('blocked'))
                    }
                    return Promise.resolve(ok(input))
                }
            )

            const pipeline = createSessionReplayPipeline({
                kafkaProducer: mockKafkaProducer as unknown as KafkaProducerWrapper,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                dlqTopic: 'dlq-topic',
                promiseScheduler,
                teamService: mockTeamService,
            })

            const messages = [
                createMessage(0, 1, 'session-1'),
                createMessage(0, 2, 'session-2'),
                createMessage(0, 3, 'session-3'),
            ]

            const result = await runSessionReplayPipeline(pipeline, messages)

            expect(result).toHaveLength(2)
            expect(result[0].parsedMessage.session_id).toBe('session-1')
            expect(result[1].parsedMessage.session_id).toBe('session-3')
        })

        it('filters out messages that fail to parse', async () => {
            const pipeline = createSessionReplayPipeline({
                kafkaProducer: mockKafkaProducer as unknown as KafkaProducerWrapper,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                dlqTopic: 'dlq-topic',
                promiseScheduler,
                teamService: mockTeamService,
            })

            // Create a message with invalid payload
            const invalidMessage: Message = {
                partition: 0,
                offset: 2,
                topic: 'test-topic',
                value: Buffer.from('invalid json'),
                key: Buffer.from('test-key'),
                timestamp: Date.now(),
                headers: [],
                size: 12,
            }

            const messages = [createMessage(0, 1, 'session-1'), invalidMessage, createMessage(0, 3, 'session-3')]

            const result = await runSessionReplayPipeline(pipeline, messages)

            expect(result).toHaveLength(2)
            expect(result[0].parsedMessage.session_id).toBe('session-1')
            expect(result[1].parsedMessage.session_id).toBe('session-3')
        })

        it('sends messages that fail to parse to the DLQ topic', async () => {
            const pipeline = createSessionReplayPipeline({
                kafkaProducer: mockKafkaProducer as unknown as KafkaProducerWrapper,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                dlqTopic: 'dlq-topic',
                promiseScheduler,
            })

            // Create a message with invalid payload
            const invalidMessage: Message = {
                partition: 0,
                offset: 2,
                topic: 'test-topic',
                value: Buffer.from('invalid json'),
                key: Buffer.from('test-key'),
                timestamp: Date.now(),
                headers: [],
                size: 12,
            }

            const messages = [invalidMessage]

            await runSessionReplayPipeline(pipeline, messages)

            // Wait for side effects to complete
            await promiseScheduler.waitForAll()

            // Verify the message was sent to the DLQ topic
            expect(mockKafkaProducer.produce).toHaveBeenCalledWith(
                expect.objectContaining({
                    topic: 'dlq-topic',
                    value: invalidMessage.value,
                })
            )
        })

        it('redirects overflow messages and filters them out', async () => {
            mockCreateApplyEventRestrictionsStep.mockReturnValue(
                (input: { message: Message; headers: Record<string, string> }) => {
                    if (input.message.offset === 2) {
                        return Promise.resolve(redirect('overflow', 'overflow-topic', true, false))
                    }
                    return Promise.resolve(ok(input))
                }
            )

            const pipeline = createSessionReplayPipeline({
                kafkaProducer: mockKafkaProducer as unknown as KafkaProducerWrapper,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                dlqTopic: 'dlq-topic',
                promiseScheduler,
                teamService: mockTeamService,
            })

            const messages = [
                createMessage(0, 1, 'session-1'),
                createMessage(0, 2, 'session-2'),
                createMessage(0, 3, 'session-3'),
            ]

            const result = await runSessionReplayPipeline(pipeline, messages)

            // Wait for side effects to complete
            await promiseScheduler.waitForAll()

            expect(result).toHaveLength(2)
            expect(result[0].parsedMessage.session_id).toBe('session-1')
            expect(result[1].parsedMessage.session_id).toBe('session-3')

            // Verify the overflow message was produced
            expect(mockKafkaProducer.produce).toHaveBeenCalledWith(
                expect.objectContaining({
                    topic: 'overflow-topic',
                })
            )
        })

        it('returns empty array for empty input', async () => {
            const pipeline = createSessionReplayPipeline({
                kafkaProducer: mockKafkaProducer as unknown as KafkaProducerWrapper,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                dlqTopic: 'dlq-topic',
                promiseScheduler,
                teamService: mockTeamService,
            })

            const result = await runSessionReplayPipeline(pipeline, [])

            expect(result).toHaveLength(0)
        })

        it('processes large batch with mixed dropped and passed messages correctly', async () => {
            // Drop every 10th message via restrictions
            mockCreateApplyEventRestrictionsStep.mockReturnValue(
                (input: { message: Message; headers: Record<string, string> }) => {
                    if (input.message.offset % 10 === 0) {
                        return Promise.resolve(drop('blocked'))
                    }
                    return Promise.resolve(ok(input))
                }
            )

            const pipeline = createSessionReplayPipeline({
                kafkaProducer: mockKafkaProducer as unknown as KafkaProducerWrapper,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                dlqTopic: 'dlq-topic',
                promiseScheduler,
                teamService: mockTeamService,
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
            const resultSessionIds = result.map((m) => m.parsedMessage.session_id)
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
            mockCreateApplyEventRestrictionsStep.mockReturnValue(
                (input: { message: Message; headers: Record<string, string> }) => {
                    capturedHeaders.push(input.headers)
                    return Promise.resolve(ok(input))
                }
            )

            const pipeline = createSessionReplayPipeline({
                kafkaProducer: mockKafkaProducer as unknown as KafkaProducerWrapper,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                dlqTopic: 'dlq-topic',
                promiseScheduler,
                teamService: mockTeamService,
            })

            const messages = [
                createMessage(0, 1, 'session-1', { token: 'team-token-123', distinctId: 'user-456' }),
                createMessage(0, 2, 'session-2', { token: 'team-token-789' }),
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
                kafkaProducer: mockKafkaProducer as unknown as KafkaProducerWrapper,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                dlqTopic: 'dlq-topic',
                promiseScheduler,
                teamService: mockTeamService,
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
                expect(result[i].parsedMessage.session_id).toBe(`session-${i + 1}`)
            }
        })

        it('filters out messages with invalid team', async () => {
            const teamServiceThatDropsSecond = {
                getTeamByToken: jest.fn().mockImplementation((token: string) => {
                    if (token === 'invalid-token') {
                        return Promise.resolve(null)
                    }
                    return Promise.resolve(defaultTeam)
                }),
                getRetentionPeriodByTeamId: jest.fn().mockResolvedValue(30),
            } as unknown as TeamService

            const pipeline = createSessionReplayPipeline({
                kafkaProducer: mockKafkaProducer as unknown as KafkaProducerWrapper,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                dlqTopic: 'dlq-topic',
                promiseScheduler,
                teamService: teamServiceThatDropsSecond,
            })

            const messages = [
                createMessage(0, 1, 'session-1', { token: 'valid-token' }),
                createMessage(0, 2, 'session-2', { token: 'invalid-token' }),
                createMessage(0, 3, 'session-3', { token: 'valid-token' }),
            ]

            const result = await runSessionReplayPipeline(pipeline, messages)

            expect(result).toHaveLength(2)
            expect(result[0].parsedMessage.session_id).toBe('session-1')
            expect(result[1].parsedMessage.session_id).toBe('session-3')
        })

        it('sends messages with no token header to DLQ', async () => {
            const pipeline = createSessionReplayPipeline({
                kafkaProducer: mockKafkaProducer as unknown as KafkaProducerWrapper,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                overflowTopic: 'overflow-topic',
                promiseScheduler,
                teamService: mockTeamService,
            })

            // Explicitly pass empty headers (no token)
            const messages = [createMessage(0, 1, 'session-1', {})]

            const result = await runSessionReplayPipeline(pipeline, messages)

            // Message should be dropped by team filter due to missing token
            expect(result).toHaveLength(0)
        })
    })
})
