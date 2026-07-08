import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT, OVERFLOW_OUTPUT } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { parseJSON } from '~/common/utils/json-parse'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'
import { createOkContext } from '~/ingestion/framework/helpers'
import { drop, isOkResult, ok, redirect } from '~/ingestion/framework/results'
import { SessionBatchRecorder } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'
import { SessionFilter } from '~/ingestion/pipelines/sessionreplay/sessions/session-filter'
import { SessionTracker } from '~/ingestion/pipelines/sessionreplay/sessions/session-tracker'
import {
    RetentionResolution,
    RetentionService,
} from '~/ingestion/pipelines/sessionreplay/shared/retention/retention-service'
import { SessionMap, SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { createMockKeyStore } from '~/ingestion/pipelines/sessionreplay/shared/test-helpers'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'

import { KafkaOffsetManager } from './kafka/offset-manager'
import { TrimmedReplayElement } from './session-batch-post-process-step'
import { SessionReplayInnerPipelineConfig, createSessionReplayInnerPipeline } from './session-replay-pipeline'

jest.mock('~/ingestion/common/steps/event-preprocessing', () => ({
    createParseHeadersStep: jest.fn(),
    createApplyEventRestrictionsStep: jest.fn(),
}))

function createMockBatchRecorder(): jest.Mocked<SessionBatchRecorder> {
    return {
        record: jest.fn().mockResolvedValue(undefined),
        getRetention: jest.fn().mockReturnValue(undefined),
        size: 0,
    } as unknown as jest.Mocked<SessionBatchRecorder>
}

const mockCreateParseHeadersStep = createParseHeadersStep as jest.Mock
const mockCreateApplyEventRestrictionsStep = createApplyEventRestrictionsStep as jest.Mock

interface MockRecorder {
    record: jest.Mock
}

interface MockTopHogRegistry extends TopHogRegistry {
    sumRecorders: Map<string, MockRecorder>
    maxRecorders: Map<string, MockRecorder>
    averageRecorders: Map<string, MockRecorder>
}

function createMockTopHog(): MockTopHogRegistry {
    const sumRecorders = new Map<string, MockRecorder>()
    const maxRecorders = new Map<string, MockRecorder>()
    const averageRecorders = new Map<string, MockRecorder>()

    return {
        sumRecorders,
        maxRecorders,
        averageRecorders,
        registerSum: jest.fn().mockImplementation((name: string) => {
            const recorder = { record: jest.fn() }
            sumRecorders.set(name, recorder)
            return recorder
        }),
        registerMax: jest.fn().mockImplementation((name: string) => {
            const recorder = { record: jest.fn() }
            maxRecorders.set(name, recorder)
            return recorder
        }),
        registerAverage: jest.fn().mockImplementation((name: string) => {
            const recorder = { record: jest.fn() }
            averageRecorders.set(name, recorder)
            return recorder
        }),
    }
}

describe('session-replay-pipeline', () => {
    let mockRestrictionManager: EventIngestionRestrictionManager
    let mockTeamService: TeamService
    let mockBatchRecorder: jest.Mocked<SessionBatchRecorder>
    let mockOffsetManager: jest.Mocked<KafkaOffsetManager>
    let promiseScheduler: PromiseScheduler
    let topHog: MockTopHogRegistry
    let outputs: jest.Mocked<
        IngestionOutputs<typeof DLQ_OUTPUT | typeof OVERFLOW_OUTPUT | typeof INGESTION_WARNINGS_OUTPUT>
    >

    // Debug logging disabled by default in tests
    const isDebugLoggingEnabled = () => false

    // Resolves every session to 30d so messages flow through to recording.
    const retentionService = {
        resolveSessionRetentions: jest.fn().mockImplementation((sessions: SessionSet) => {
            const resolutions = new SessionMap<RetentionResolution>()
            for (const s of sessions) {
                resolutions.set(s.teamId, s.sessionId, { resolved: true, retentionPeriod: '30d' })
            }
            return Promise.resolve(resolutions)
        }),
    } as unknown as RetentionService

    // Every session resolves as already-seen, unblocked, and with a cleartext key so messages flow
    // through to recording.
    const sessionTracker = {
        hasSeen: jest.fn().mockImplementation((sessions: SessionSet) => {
            const map = new SessionMap<boolean>()
            for (const { teamId, sessionId } of sessions) {
                map.set(teamId, sessionId, true)
            }
            return Promise.resolve(map)
        }),
        markSeen: jest.fn().mockResolvedValue(undefined),
    } as unknown as SessionTracker
    const sessionFilter = {
        handleNewSessions: jest.fn().mockResolvedValue(new SessionSet()),
        isBlocked: jest.fn().mockResolvedValue(new SessionSet()),
    } as unknown as SessionFilter
    const keyStore = createMockKeyStore()

    const defaultTeam: TeamForReplay = {
        teamId: 1,
        consoleLogIngestionEnabled: false,
        aiTrainingOptedIn: true,
        firstPartyHosts: [],
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

    function createOldTimestampSnapshotPayload(sessionId: string, daysOld: number): string {
        const oldTimestamp = now.minus({ days: daysOld })
        const event = {
            event: '$snapshot_items',
            properties: {
                $session_id: sessionId,
                $window_id: 'window-1',
                $snapshot_items: [
                    { type: 2, timestamp: oldTimestamp.toMillis(), data: {} },
                    { type: 3, timestamp: oldTimestamp.plus({ seconds: 1 }).toMillis(), data: {} },
                ],
            },
        }
        const rawMessage = {
            distinct_id: 'user-123',
            data: JSON.stringify(event),
        }
        return JSON.stringify(rawMessage)
    }

    // Builds the inner pipeline with the shared mocks; per-test overrides (e.g. a different team
    // service) are merged in.
    function buildPipeline(
        overrides: Partial<SessionReplayInnerPipelineConfig> = {}
    ): ReturnType<typeof createSessionReplayInnerPipeline> {
        return createSessionReplayInnerPipeline({
            outputs,
            eventIngestionRestrictionManager: mockRestrictionManager,
            overflowEnabled: true,
            promiseScheduler,
            offsetManager: mockOffsetManager,
            teamService: mockTeamService,
            retentionService,
            sessionTracker,
            sessionFilter,
            keyStore,
            sessionKeyResolutionMaxConcurrency: 20,
            topHog,
            isDebugLoggingEnabled,
            ...overrides,
        })
    }

    // Feeds messages through the inner pipeline with the batch recorder tagged on each element
    // (as the accumulating pipeline does), drains its batch results, and returns the unwrapped OK
    // outputs — now the trimmed per-message rows the afterBatch emits (in feed order).
    async function runPipeline(
        pipeline: ReturnType<typeof createSessionReplayInnerPipeline>,
        messages: Message[]
    ): Promise<TrimmedReplayElement[]> {
        // The accumulating pipeline skips empty feeds (an empty batch never completes); mirror that.
        if (messages.length > 0) {
            await pipeline.feed(
                messages.map((message) =>
                    createOkContext({ message, sessionBatchRecorder: mockBatchRecorder, batchId: 0 }, { message })
                )
            )
        }
        const results: TrimmedReplayElement[] = []
        let batch = await pipeline.next()
        while (batch !== null) {
            for (const element of batch.elements) {
                if (isOkResult(element.result)) {
                    results.push(element.result.value)
                }
            }
            batch = await pipeline.next()
        }
        return results
    }

    // The session ids recorded into the batch, in call order — the observable effect of a message
    // reaching the record step (the trimmed output no longer carries the parsed message).
    function recordedSessionIds(): string[] {
        return mockBatchRecorder.record.mock.calls.map((call) => call[0].message.session_id)
    }

    beforeEach(() => {
        jest.clearAllMocks()

        outputs = createMockIngestionOutputs<
            typeof DLQ_OUTPUT | typeof OVERFLOW_OUTPUT | typeof INGESTION_WARNINGS_OUTPUT
        >()

        // The restriction manager is not actually used since we mock createApplyEventRestrictionsStep
        mockRestrictionManager = {} as unknown as EventIngestionRestrictionManager

        // Default: team service validates all messages
        mockTeamService = {
            getTeamByToken: jest.fn().mockResolvedValue(defaultTeam),
            getRetentionPeriodByTeamId: jest.fn().mockResolvedValue(30),
        } as unknown as TeamService

        mockBatchRecorder = createMockBatchRecorder()
        mockOffsetManager = { trackOffset: jest.fn() } as unknown as jest.Mocked<KafkaOffsetManager>
        topHog = createMockTopHog()

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
        const actualSessionId = sessionId ?? `session-${offset}`
        // Default the headers the validate step requires; session_id/distinct_id mirror the body.
        const headersWithDefaults = headers ?? { token: 'test-token' }
        if (!headersWithDefaults.session_id) {
            headersWithDefaults.session_id = actualSessionId
        }
        if (!headersWithDefaults.distinct_id) {
            headersWithDefaults.distinct_id = 'user-123'
        }
        const kafkaHeaders = Object.entries(headersWithDefaults).map(([key, value]) => ({
            [key]: Buffer.from(value),
        }))

        const payload = createValidSnapshotPayload(actualSessionId)

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

    function createMessageWithOldTimestamps(
        partition: number,
        offset: number,
        sessionId: string,
        daysOld: number,
        headers?: Record<string, string>
    ): Message {
        const headersWithDefaults = headers ?? { token: 'test-token' }
        if (!headersWithDefaults.session_id) {
            headersWithDefaults.session_id = sessionId
        }
        if (!headersWithDefaults.distinct_id) {
            headersWithDefaults.distinct_id = 'user-123'
        }
        const kafkaHeaders = Object.entries(headersWithDefaults).map(([key, value]) => ({
            [key]: Buffer.from(value),
        }))

        const payload = createOldTimestampSnapshotPayload(sessionId, daysOld)

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

    describe('createSessionReplayInnerPipeline', () => {
        it('passes through messages when no restrictions apply', async () => {
            const pipeline = buildPipeline()

            const messages = [createMessage(0, 1, 'session-1'), createMessage(0, 2, 'session-2')]

            const result = await runPipeline(pipeline, messages)

            expect(result).toHaveLength(2)
            expect(recordedSessionIds()).toEqual(['session-1', 'session-2'])
            // trimmed output is the lightweight per-message row (in feed order), not the parsed message
            expect(result[0]).toEqual({ partition: 0, timestamp: expect.any(Number) })
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

            const pipeline = buildPipeline()

            const messages = [
                createMessage(0, 1, 'session-1'),
                createMessage(0, 2, 'session-2'),
                createMessage(0, 3, 'session-3'),
            ]

            const result = await runPipeline(pipeline, messages)

            expect(result).toHaveLength(2)
            expect(recordedSessionIds()).toEqual(['session-1', 'session-3'])
        })

        it('filters out messages that fail to parse', async () => {
            const pipeline = buildPipeline()

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

            const result = await runPipeline(pipeline, messages)

            expect(result).toHaveLength(2)
            expect(recordedSessionIds()).toEqual(['session-1', 'session-3'])
        })

        it('sends messages that fail to parse to the DLQ topic', async () => {
            const pipeline = buildPipeline()

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

            await runPipeline(pipeline, messages)

            // Wait for side effects to complete
            await promiseScheduler.waitForAll()

            // Verify the message was sent to the DLQ output
            expect(outputs.produce).toHaveBeenCalledWith(
                DLQ_OUTPUT,
                expect.objectContaining({
                    value: invalidMessage.value,
                })
            )
        })

        it('redirects overflow messages and filters them out', async () => {
            mockCreateApplyEventRestrictionsStep.mockReturnValue(
                (input: { message: Message; headers: Record<string, string> }) => {
                    if (input.message.offset === 2) {
                        return Promise.resolve(redirect('overflow', OVERFLOW_OUTPUT, true, false))
                    }
                    return Promise.resolve(ok(input))
                }
            )

            const pipeline = buildPipeline()

            const messages = [
                createMessage(0, 1, 'session-1'),
                createMessage(0, 2, 'session-2'),
                createMessage(0, 3, 'session-3'),
            ]

            const result = await runPipeline(pipeline, messages)

            // Wait for side effects to complete
            await promiseScheduler.waitForAll()

            expect(result).toHaveLength(2)
            expect(recordedSessionIds()).toEqual(['session-1', 'session-3'])

            // Verify the overflow message was produced
            expect(outputs.produce).toHaveBeenCalledWith(OVERFLOW_OUTPUT, expect.anything())
        })

        it('returns empty array for empty input', async () => {
            const pipeline = buildPipeline()

            const result = await runPipeline(pipeline, [])

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

            const pipeline = buildPipeline()

            // Create 1000 messages
            const messages: Message[] = []
            for (let i = 1; i <= 1000; i++) {
                messages.push(createMessage(0, i))
            }

            const result = await runPipeline(pipeline, messages)

            // 100 messages should be dropped (10, 20, 30, ..., 1000)
            // 900 messages should pass through
            expect(result).toHaveLength(900)

            // Verify the recorded session_ids are correct (all non-multiples of 10)
            const resultSessionIds = recordedSessionIds()
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

            const pipeline = buildPipeline()

            const messages = [
                createMessage(0, 1, 'session-1', { token: 'team-token-123', distinctId: 'user-456' }),
                createMessage(0, 2, 'session-2', { token: 'team-token-789' }),
            ]

            const result = await runPipeline(pipeline, messages)

            expect(result).toHaveLength(2)
            // Verify headers were correctly parsed and passed through
            expect(capturedHeaders).toHaveLength(2)
            expect(capturedHeaders[0]).toEqual({
                token: 'team-token-123',
                distinctId: 'user-456',
                session_id: 'session-1',
                distinct_id: 'user-123',
            })
            expect(capturedHeaders[1]).toEqual({
                token: 'team-token-789',
                session_id: 'session-2',
                distinct_id: 'user-123',
            })
        })

        it('processes large batch with all messages passing through', async () => {
            const pipeline = buildPipeline()

            // Create 500 messages
            const messages: Message[] = []
            for (let i = 1; i <= 500; i++) {
                messages.push(createMessage(0, i))
            }

            const result = await runPipeline(pipeline, messages)

            expect(result).toHaveLength(500)

            // Verify all session_ids were recorded, in feed order
            expect(recordedSessionIds()).toEqual(Array.from({ length: 500 }, (_, i) => `session-${i + 1}`))
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

            const pipeline = buildPipeline({ teamService: teamServiceThatDropsSecond })

            const messages = [
                createMessage(0, 1, 'session-1', { token: 'valid-token' }),
                createMessage(0, 2, 'session-2', { token: 'invalid-token' }),
                createMessage(0, 3, 'session-3', { token: 'valid-token' }),
            ]

            const result = await runPipeline(pipeline, messages)

            expect(result).toHaveLength(2)
            expect(recordedSessionIds()).toEqual(['session-1', 'session-3'])
        })

        it('sends messages with no token header to DLQ', async () => {
            const pipeline = buildPipeline()

            // Explicitly pass empty headers (no token)
            const messages = [createMessage(0, 1, 'session-1', {})]

            const result = await runPipeline(pipeline, messages)

            // Message should be dropped by header validation due to missing token
            expect(result).toHaveLength(0)
        })

        it('sends ingestion warning for old lib version', async () => {
            const pipeline = buildPipeline()

            const messages = [createMessage(0, 1, 'session-1', { token: 'test-token', lib_version: '1.74.0' })]

            const result = await runPipeline(pipeline, messages)

            expect(result).toHaveLength(1)
            expect(outputs.queueMessages).toHaveBeenCalledTimes(1)

            expect(outputs.queueMessages).toHaveBeenCalledWith(
                INGESTION_WARNINGS_OUTPUT,
                expect.arrayContaining([
                    expect.objectContaining({
                        value: expect.any(Buffer),
                    }),
                ])
            )
            const warningMessages = outputs.queueMessages.mock.calls[0][1]
            const messageValue = parseJSON(warningMessages[0].value!.toString())
            expect(messageValue.team_id).toBe(1)
            expect(messageValue.type).toBe('replay_lib_version_too_old')
            expect(parseJSON(messageValue.details)).toEqual({
                libVersion: '1.74.0',
                parsedVersion: { major: 1, minor: 74 },
            })
        })

        it('does not send ingestion warning for new lib version', async () => {
            const pipeline = buildPipeline()

            const messages = [createMessage(0, 1, 'session-1', { token: 'test-token', lib_version: '1.75.0' })]

            const result = await runPipeline(pipeline, messages)

            expect(result).toHaveLength(1)
            expect(outputs.queueMessages).not.toHaveBeenCalled()
        })

        it('does not send ingestion warning when no lib version header', async () => {
            const pipeline = buildPipeline()

            const messages = [createMessage(0, 1, 'session-1', { token: 'test-token' })]

            const result = await runPipeline(pipeline, messages)

            expect(result).toHaveLength(1)
            expect(outputs.queueMessages).not.toHaveBeenCalled()
        })

        it('sends ingestion warning when message timestamps are too old', async () => {
            const pipeline = buildPipeline()

            // Create a message with timestamps 10 days old (threshold is 7 days)
            const messages = [createMessageWithOldTimestamps(0, 1, 'session-1', 10, { token: 'test-token' })]

            const result = await runPipeline(pipeline, messages)

            // Message should be dropped but warning should be sent
            expect(result).toHaveLength(0)
            expect(outputs.queueMessages).toHaveBeenCalledTimes(1)

            expect(outputs.queueMessages).toHaveBeenCalledWith(
                INGESTION_WARNINGS_OUTPUT,
                expect.arrayContaining([
                    expect.objectContaining({
                        value: expect.any(Buffer),
                    }),
                ])
            )
            const warningMessages = outputs.queueMessages.mock.calls[0][1]
            const messageValue = parseJSON(warningMessages[0].value!.toString())
            expect(messageValue.team_id).toBe(1)
            expect(messageValue.type).toBe('message_timestamp_diff_too_large')
        })

        it('records messages to session batch', async () => {
            const pipeline = buildPipeline()

            const messages = [createMessage(0, 1, 'session-1')]

            await runPipeline(pipeline, messages)

            const mockBatch = mockBatchRecorder
            expect(mockBatch.record).toHaveBeenCalledTimes(1)
            expect(mockBatch.record).toHaveBeenCalledWith(
                expect.objectContaining({
                    team: defaultTeam,
                    message: expect.objectContaining({
                        session_id: 'session-1',
                    }),
                }),
                '30d',
                expect.objectContaining({ sessionState: 'cleartext' })
            )
        })

        it('records multiple messages to session batch', async () => {
            const pipeline = buildPipeline()

            const messages = [
                createMessage(0, 1, 'session-1'),
                createMessage(0, 2, 'session-2'),
                createMessage(0, 3, 'session-3'),
            ]

            await runPipeline(pipeline, messages)

            const mockBatch = mockBatchRecorder
            expect(mockBatch.record).toHaveBeenCalledTimes(3)
        })

        it('tracks the offset of every fed message in the afterBatch, including dropped ones', async () => {
            // Drop offset 2 at restrictions; offsets 1 and 3 record.
            mockCreateApplyEventRestrictionsStep.mockReturnValue(
                (input: { message: Message; headers: Record<string, string> }) => {
                    if (input.message.offset === 2) {
                        return Promise.resolve(drop('blocked'))
                    }
                    return Promise.resolve(ok(input))
                }
            )

            const pipeline = buildPipeline()
            const messages = [
                createMessage(0, 1, 'session-1'),
                createMessage(0, 2, 'session-2'),
                createMessage(0, 3, 'session-3'),
            ]

            const result = await runPipeline(pipeline, messages)

            // Only the recorded messages surface as trimmed rows, in feed order.
            expect(result).toEqual([
                { partition: 0, timestamp: expect.any(Number) },
                { partition: 0, timestamp: expect.any(Number) },
            ])
            // Every fed message's offset is tracked (so the dropped one advances too).
            expect(mockOffsetManager.trackOffset.mock.calls.map((call) => call[0])).toEqual([
                { partition: 0, offset: 1 },
                { partition: 0, offset: 2 },
                { partition: 0, offset: 3 },
            ])
        })

        it('does not record dropped messages to session batch', async () => {
            // Drop every message via restrictions
            mockCreateApplyEventRestrictionsStep.mockReturnValue(() => Promise.resolve(drop('dropped by restriction')))

            const pipeline = buildPipeline()

            const messages = [createMessage(0, 1, 'session-1')]

            const result = await runPipeline(pipeline, messages)

            expect(result).toHaveLength(0)
            const mockBatch = mockBatchRecorder
            expect(mockBatch.record).not.toHaveBeenCalled()
        })

        it('does not record messages with invalid team to session batch', async () => {
            const teamServiceThatReturnsNull = {
                getTeamByToken: jest.fn().mockResolvedValue(null),
            } as unknown as TeamService

            const pipeline = buildPipeline({ teamService: teamServiceThatReturnsNull })

            const messages = [createMessage(0, 1, 'session-1', { token: 'invalid-token' })]

            const result = await runPipeline(pipeline, messages)

            expect(result).toHaveLength(0)
            const mockBatch = mockBatchRecorder
            expect(mockBatch.record).not.toHaveBeenCalled()
        })

        it('records parse time metric via TopHog', async () => {
            const pipeline = buildPipeline()

            const messages = [createMessage(0, 1, 'session-1', { token: 'test-token' })]

            await runPipeline(pipeline, messages)

            // Verify parse time metric was registered and recorded
            const parseTimeRecorder = topHog.sumRecorders.get('parse_time_ms_by_session_id')
            expect(parseTimeRecorder).toBeDefined()
            expect(parseTimeRecorder!.record).toHaveBeenCalledTimes(1)
            expect(parseTimeRecorder!.record).toHaveBeenCalledWith(
                { token: 'test-token', session_id: 'session-1' },
                expect.any(Number)
            )
        })

        it('records message size metric via TopHog', async () => {
            const pipeline = buildPipeline()

            const messages = [createMessage(0, 1, 'session-1', { token: 'test-token' })]

            await runPipeline(pipeline, messages)

            // Verify message size metric was registered and recorded
            const messageSizeRecorder = topHog.sumRecorders.get('message_size_by_session_id')
            expect(messageSizeRecorder).toBeDefined()
            expect(messageSizeRecorder!.record).toHaveBeenCalledTimes(1)
            expect(messageSizeRecorder!.record).toHaveBeenCalledWith(
                { token: 'test-token', session_id: 'session-1' },
                expect.any(Number) // message size
            )
        })

        it('records consume time metric via TopHog', async () => {
            const pipeline = buildPipeline()

            const messages = [createMessage(0, 1, 'session-1', { token: 'test-token' })]

            await runPipeline(pipeline, messages)

            // Verify consume time metric was registered and recorded
            const consumeTimeRecorder = topHog.sumRecorders.get('consume_time_ms_by_session_id')
            expect(consumeTimeRecorder).toBeDefined()
            expect(consumeTimeRecorder!.record).toHaveBeenCalledTimes(1)
            expect(consumeTimeRecorder!.record).toHaveBeenCalledWith(
                { token: 'test-token', session_id: 'session-1' },
                expect.any(Number) // timing in ms
            )
        })

        it('records TopHog metrics for multiple messages', async () => {
            const pipeline = buildPipeline()

            const messages = [
                createMessage(0, 1, 'session-1', { token: 'token-1' }),
                createMessage(0, 2, 'session-2', { token: 'token-2' }),
                createMessage(0, 3, 'session-3', { token: 'token-1' }),
            ]

            await runPipeline(pipeline, messages)

            // Verify all three messages were recorded for each metric
            const parseTimeRecorder = topHog.sumRecorders.get('parse_time_ms_by_session_id')
            expect(parseTimeRecorder!.record).toHaveBeenCalledTimes(3)

            const messageSizeRecorder = topHog.sumRecorders.get('message_size_by_session_id')
            expect(messageSizeRecorder!.record).toHaveBeenCalledTimes(3)

            const consumeTimeRecorder = topHog.sumRecorders.get('consume_time_ms_by_session_id')
            expect(consumeTimeRecorder!.record).toHaveBeenCalledTimes(3)

            // Verify different session_ids and tokens are recorded
            expect(parseTimeRecorder!.record).toHaveBeenCalledWith(
                { token: 'token-1', session_id: 'session-1' },
                expect.any(Number)
            )
            expect(parseTimeRecorder!.record).toHaveBeenCalledWith(
                { token: 'token-2', session_id: 'session-2' },
                expect.any(Number)
            )
            expect(parseTimeRecorder!.record).toHaveBeenCalledWith(
                { token: 'token-1', session_id: 'session-3' },
                expect.any(Number)
            )
        })

        it('does not record TopHog metrics for dropped messages', async () => {
            mockCreateApplyEventRestrictionsStep.mockReturnValue(() => Promise.resolve(drop('dropped')))

            const pipeline = buildPipeline()

            const messages = [createMessage(0, 1, 'session-1')]

            await runPipeline(pipeline, messages)

            // Metrics should not be recorded for dropped messages since they never reach the steps
            const parseTimeRecorder = topHog.sumRecorders.get('parse_time_ms_by_session_id')
            const messageSizeRecorder = topHog.sumRecorders.get('message_size_by_session_id')
            const consumeTimeRecorder = topHog.sumRecorders.get('consume_time_ms_by_session_id')

            // Recorders might not even be created if no messages reach the step
            if (parseTimeRecorder) {
                expect(parseTimeRecorder.record).not.toHaveBeenCalled()
            }
            if (messageSizeRecorder) {
                expect(messageSizeRecorder.record).not.toHaveBeenCalled()
            }
            if (consumeTimeRecorder) {
                expect(consumeTimeRecorder.record).not.toHaveBeenCalled()
            }
        })

        it('uses "unknown" token in TopHog metrics when token header is missing', async () => {
            // Override parse headers to not include token in parsed headers, but still have it in message headers
            mockCreateParseHeadersStep.mockReturnValue(
                (input: { message: Message; headers?: Record<string, string> }) => {
                    // session_id/distinct_id must be present (validate) and mirror the body (parse consistency check)
                    return Promise.resolve(
                        ok({
                            ...input,
                            headers: { token: 'test-token', session_id: 'session-1', distinct_id: 'user-123' },
                        })
                    )
                }
            )

            const pipeline = buildPipeline()

            // Create message without token in Kafka headers (the token parsed from headers is used for team lookup,
            // but the token in the parsed message comes from Kafka headers)
            const messageWithoutToken: Message = {
                partition: 0,
                offset: 1,
                topic: 'test-topic',
                value: Buffer.from(createValidSnapshotPayload('session-1')),
                key: Buffer.from('test-key'),
                timestamp: Date.now(),
                headers: [{ token: Buffer.from('test-token') }], // Token for team lookup
                size: 100,
            }

            await runPipeline(pipeline, [messageWithoutToken])

            // The parsed message should have token from Kafka headers
            const messageSizeRecorder = topHog.sumRecorders.get('message_size_by_session_id')
            expect(messageSizeRecorder).toBeDefined()
            expect(messageSizeRecorder!.record).toHaveBeenCalledWith(
                { token: 'test-token', session_id: 'session-1' },
                expect.any(Number)
            )
        })
    })
})
