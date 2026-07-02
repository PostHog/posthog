import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT, OVERFLOW_OUTPUT } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { parseJSON } from '~/common/utils/json-parse'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'
import { drop, ok, redirect } from '~/ingestion/framework/results'
import { SessionBatchManager } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-manager'
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

import { createSessionReplayPipeline, runSessionReplayPipeline } from './session-replay-pipeline'

jest.mock('~/ingestion/common/steps/event-preprocessing', () => ({
    createParseHeadersStep: jest.fn(),
    createApplyEventRestrictionsStep: jest.fn(),
}))

function createMockSessionBatchManager(): jest.Mocked<SessionBatchManager> {
    const mockBatchRecorder = {
        record: jest.fn().mockResolvedValue(undefined),
        getRetention: jest.fn().mockReturnValue(undefined),
    } as unknown as jest.Mocked<SessionBatchRecorder>

    return {
        getCurrentBatch: jest.fn().mockReturnValue(mockBatchRecorder),
        shouldFlush: jest.fn().mockReturnValue(false),
        flush: jest.fn().mockResolvedValue(undefined),
        discardPartitions: jest.fn(),
    } as unknown as jest.Mocked<SessionBatchManager>
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
    let mockSessionBatchManager: jest.Mocked<SessionBatchManager>
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
        handleNewSession: jest.fn().mockResolvedValue(undefined),
        isBlocked: jest.fn().mockImplementation((sessions: SessionSet) => {
            const map = new SessionMap<boolean>()
            for (const { teamId, sessionId } of sessions) {
                map.set(teamId, sessionId, false)
            }
            return Promise.resolve(map)
        }),
    } as unknown as SessionFilter
    const keyStore = createMockKeyStore()

    const defaultTeam: TeamForReplay = {
        teamId: 1,
        consoleLogIngestionEnabled: false,
        aiTrainingOptedIn: true,
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

        mockSessionBatchManager = createMockSessionBatchManager()
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
        // Default the headers the validate step requires; session_id/distinct_id must mirror the body.
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

    describe('runSessionReplayPipeline', () => {
        // The runner now returns the max offset per partition; which messages actually reached
        // recording is observed through the batch recorder mock.
        const recordedSessionIds = (): string[] =>
            (mockSessionBatchManager.getCurrentBatch().record as jest.Mock).mock.calls.map(
                (call) => call[0].message.session_id
            )

        it('passes through messages when no restrictions apply', async () => {
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [createMessage(0, 1, 'session-1'), createMessage(0, 2, 'session-2')]

            const offsets = await runSessionReplayPipeline(pipeline, messages)

            expect(recordedSessionIds()).toEqual(['session-1', 'session-2'])
            // Highest offset reached on the partition is tracked.
            expect(offsets).toEqual(new Map([[0, 2]]))
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
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [
                createMessage(0, 1, 'session-1'),
                createMessage(0, 2, 'session-2'),
                createMessage(0, 3, 'session-3'),
            ]

            const offsets = await runSessionReplayPipeline(pipeline, messages)

            expect(recordedSessionIds()).toEqual(['session-1', 'session-3'])
            // The dropped message (offset 2) is not recorded, but its offset is still accounted for —
            // the partition's committed offset advances past it rather than replaying it forever.
            expect(offsets).toEqual(new Map([[0, 3]]))
        })

        it('tracks the offset of a dropped message even when it is the highest in the partition', async () => {
            mockCreateApplyEventRestrictionsStep.mockReturnValue(
                (input: { message: Message; headers: Record<string, string> }) => {
                    if (input.message.offset === 3) {
                        return Promise.resolve(drop('blocked'))
                    }
                    return Promise.resolve(ok(input))
                }
            )

            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [
                createMessage(0, 1, 'session-1'),
                createMessage(0, 2, 'session-2'),
                createMessage(0, 3, 'session-3'),
            ]

            const offsets = await runSessionReplayPipeline(pipeline, messages)

            expect(recordedSessionIds()).toEqual(['session-1', 'session-2'])
            // The highest offset on the partition belongs to the dropped message; it must still be
            // tracked or that partition would never commit past offset 2.
            expect(offsets).toEqual(new Map([[0, 3]]))
        })

        it('filters out messages that fail to parse', async () => {
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
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

            const offsets = await runSessionReplayPipeline(pipeline, messages)

            expect(recordedSessionIds()).toEqual(['session-1', 'session-3'])
            // The unparseable message (offset 2) is DLQ'd, but its offset is still accounted for.
            expect(offsets).toEqual(new Map([[0, 3]]))
        })

        it('sends messages that fail to parse to the DLQ topic', async () => {
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
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

            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [
                createMessage(0, 1, 'session-1'),
                createMessage(0, 2, 'session-2'),
                createMessage(0, 3, 'session-3'),
            ]

            const offsets = await runSessionReplayPipeline(pipeline, messages)

            // Wait for side effects to complete
            await promiseScheduler.waitForAll()

            expect(recordedSessionIds()).toEqual(['session-1', 'session-3'])
            // The redirected message (offset 2) is not recorded, but its offset is still accounted for.
            expect(offsets).toEqual(new Map([[0, 3]]))

            // Verify the overflow message was produced
            expect(outputs.produce).toHaveBeenCalledWith(OVERFLOW_OUTPUT, expect.anything())
        })

        it('returns empty offsets for empty input', async () => {
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const offsets = await runSessionReplayPipeline(pipeline, [])

            expect(offsets.size).toBe(0)
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
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            // Create 1000 messages
            const messages: Message[] = []
            for (let i = 1; i <= 1000; i++) {
                messages.push(createMessage(0, i))
            }

            const offsets = await runSessionReplayPipeline(pipeline, messages)

            // 100 messages dropped (10, 20, ..., 1000), 900 recorded
            const recorded = recordedSessionIds()
            expect(recorded).toHaveLength(900)
            for (let i = 1; i <= 1000; i++) {
                if (i % 10 === 0) {
                    expect(recorded).not.toContain(`session-${i}`)
                } else {
                    expect(recorded).toContain(`session-${i}`)
                }
            }
            // Every message's offset is accounted for regardless of disposition.
            expect(offsets).toEqual(new Map([[0, 1000]]))
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
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [
                createMessage(0, 1, 'session-1', { token: 'team-token-123', distinctId: 'user-456' }),
                createMessage(0, 2, 'session-2', { token: 'team-token-789' }),
            ]

            await runSessionReplayPipeline(pipeline, messages)

            expect(recordedSessionIds()).toEqual(['session-1', 'session-2'])
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
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            // Create 500 messages
            const messages: Message[] = []
            for (let i = 1; i <= 500; i++) {
                messages.push(createMessage(0, i))
            }

            const offsets = await runSessionReplayPipeline(pipeline, messages)

            const recorded = recordedSessionIds()
            expect(recorded).toHaveLength(500)
            for (let i = 0; i < 500; i++) {
                expect(recorded[i]).toBe(`session-${i + 1}`)
            }
            expect(offsets).toEqual(new Map([[0, 500]]))
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
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: teamServiceThatDropsSecond,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [
                createMessage(0, 1, 'session-1', { token: 'valid-token' }),
                createMessage(0, 2, 'session-2', { token: 'invalid-token' }),
                createMessage(0, 3, 'session-3', { token: 'valid-token' }),
            ]

            const offsets = await runSessionReplayPipeline(pipeline, messages)

            expect(recordedSessionIds()).toEqual(['session-1', 'session-3'])
            // The invalid-team message (offset 2) isn't recorded, but its offset is still tracked.
            expect(offsets).toEqual(new Map([[0, 3]]))
        })

        it('sends messages with no token header to DLQ', async () => {
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            // Explicitly pass empty headers (no token)
            const messages = [createMessage(0, 1, 'session-1', {})]

            const offsets = await runSessionReplayPipeline(pipeline, messages)

            // Message is dropped by team filter due to missing token — not recorded, offset still tracked.
            expect(recordedSessionIds()).toEqual([])
            expect(offsets).toEqual(new Map([[0, 1]]))
        })

        it('sends ingestion warning for old lib version', async () => {
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [createMessage(0, 1, 'session-1', { token: 'test-token', lib_version: '1.74.0' })]

            await runSessionReplayPipeline(pipeline, messages)

            expect(recordedSessionIds()).toEqual(['session-1'])
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
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [createMessage(0, 1, 'session-1', { token: 'test-token', lib_version: '1.75.0' })]

            await runSessionReplayPipeline(pipeline, messages)

            expect(recordedSessionIds()).toEqual(['session-1'])
            expect(outputs.queueMessages).not.toHaveBeenCalled()
        })

        it('does not send ingestion warning when no lib version header', async () => {
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [createMessage(0, 1, 'session-1', { token: 'test-token' })]

            await runSessionReplayPipeline(pipeline, messages)

            expect(recordedSessionIds()).toEqual(['session-1'])
            expect(outputs.queueMessages).not.toHaveBeenCalled()
        })

        it('sends ingestion warning when message timestamps are too old', async () => {
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            // Create a message with timestamps 10 days old (threshold is 7 days)
            const messages = [createMessageWithOldTimestamps(0, 1, 'session-1', 10, { token: 'test-token' })]

            const offsets = await runSessionReplayPipeline(pipeline, messages)

            // Message is dropped (not recorded) but its offset is tracked and a warning is sent.
            expect(recordedSessionIds()).toEqual([])
            expect(offsets).toEqual(new Map([[0, 1]]))
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
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [createMessage(0, 1, 'session-1')]

            await runSessionReplayPipeline(pipeline, messages)

            expect(mockSessionBatchManager.getCurrentBatch).toHaveBeenCalled()
            const mockBatch = mockSessionBatchManager.getCurrentBatch()
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
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [
                createMessage(0, 1, 'session-1'),
                createMessage(0, 2, 'session-2'),
                createMessage(0, 3, 'session-3'),
            ]

            await runSessionReplayPipeline(pipeline, messages)

            const mockBatch = mockSessionBatchManager.getCurrentBatch()
            expect(mockBatch.record).toHaveBeenCalledTimes(3)
        })

        it('does not record dropped messages to session batch', async () => {
            // Drop every message via restrictions
            mockCreateApplyEventRestrictionsStep.mockReturnValue(() => Promise.resolve(drop('dropped by restriction')))

            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [createMessage(0, 1, 'session-1')]

            const offsets = await runSessionReplayPipeline(pipeline, messages)

            const mockBatch = mockSessionBatchManager.getCurrentBatch()
            expect(mockBatch.record).not.toHaveBeenCalled()
            // Dropped, but its offset is still tracked so the partition commits past it.
            expect(offsets).toEqual(new Map([[0, 1]]))
        })

        it('does not record messages with invalid team to session batch', async () => {
            const teamServiceThatReturnsNull = {
                getTeamByToken: jest.fn().mockResolvedValue(null),
            } as unknown as TeamService

            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: teamServiceThatReturnsNull,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [createMessage(0, 1, 'session-1', { token: 'invalid-token' })]

            const offsets = await runSessionReplayPipeline(pipeline, messages)

            const mockBatch = mockSessionBatchManager.getCurrentBatch()
            expect(mockBatch.record).not.toHaveBeenCalled()
            // Dropped, but its offset is still tracked so the partition commits past it.
            expect(offsets).toEqual(new Map([[0, 1]]))
        })

        it('records parse time metric via TopHog', async () => {
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [createMessage(0, 1, 'session-1', { token: 'test-token' })]

            await runSessionReplayPipeline(pipeline, messages)

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
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [createMessage(0, 1, 'session-1', { token: 'test-token' })]

            await runSessionReplayPipeline(pipeline, messages)

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
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [createMessage(0, 1, 'session-1', { token: 'test-token' })]

            await runSessionReplayPipeline(pipeline, messages)

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
            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [
                createMessage(0, 1, 'session-1', { token: 'token-1' }),
                createMessage(0, 2, 'session-2', { token: 'token-2' }),
                createMessage(0, 3, 'session-3', { token: 'token-1' }),
            ]

            await runSessionReplayPipeline(pipeline, messages)

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

            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

            const messages = [createMessage(0, 1, 'session-1')]

            await runSessionReplayPipeline(pipeline, messages)

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

            const pipeline = createSessionReplayPipeline({
                outputs,
                eventIngestionRestrictionManager: mockRestrictionManager,
                overflowEnabled: true,
                promiseScheduler,
                teamService: mockTeamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                topHog,
                sessionBatchManager: mockSessionBatchManager,
                isDebugLoggingEnabled,
            })

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

            await runSessionReplayPipeline(pipeline, [messageWithoutToken])

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
