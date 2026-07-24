import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'
import { ok } from '~/ingestion/framework/results'
import { runSessionReplayPipeline } from '~/ingestion/pipelines/sessionreplay'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { createParseAndAnonymizeMessageStep } from '~/ingestion/pipelines/sessionreplay/parse-and-anonymize-step'
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

import { createMlMirrorReplayPipeline } from './ml-mirror-pipeline'

jest.mock('~/ingestion/common/steps/event-preprocessing', () => ({
    createParseHeadersStep: jest.fn(),
    createApplyEventRestrictionsStep: jest.fn(),
}))
jest.mock('~/ingestion/pipelines/sessionreplay/parse-and-anonymize-step', () => ({
    createParseAndAnonymizeMessageStep: jest.fn(),
}))

const mockCreateParseHeadersStep = createParseHeadersStep as jest.Mock
const mockCreateApplyEventRestrictionsStep = createApplyEventRestrictionsStep as jest.Mock
const mockCreateParseAndAnonymizeMessageStep = createParseAndAnonymizeMessageStep as jest.Mock

describe('ml-mirror anonymize concurrency', () => {
    const now = DateTime.now()

    const retentionService = {
        resolveSessionRetentions: jest.fn().mockImplementation((sessions: SessionSet) => {
            const resolutions = new SessionMap<RetentionResolution>()
            for (const s of sessions) {
                resolutions.set(s.teamId, s.sessionId, { resolved: true, retentionPeriod: '30d' })
            }
            return Promise.resolve(resolutions)
        }),
    } as unknown as RetentionService
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
    const teamService = {
        getTeamByToken: jest.fn().mockResolvedValue({
            teamId: 1,
            consoleLogIngestionEnabled: false,
            aiTrainingOptedIn: true,
        } satisfies TeamForReplay),
        getRetentionPeriodByTeamId: jest.fn().mockResolvedValue(30),
    } as unknown as TeamService

    let recordMock: jest.Mock
    let promiseScheduler: PromiseScheduler
    // Per `${sessionId}:${offset}`: a promise the mocked scrub awaits before completing.
    let scrubGates: Map<string, Promise<void>>
    let scrubStarts: Set<string>

    beforeEach(() => {
        jest.clearAllMocks()
        recordMock = jest.fn().mockResolvedValue(undefined)
        promiseScheduler = new PromiseScheduler()
        scrubGates = new Map()
        scrubStarts = new Set()

        mockCreateParseHeadersStep.mockReturnValue((input: { message: Message }) => {
            const headers: Record<string, string> = {}
            for (const header of input.message.headers || []) {
                for (const [key, value] of Object.entries(header)) {
                    headers[key] = Buffer.isBuffer(value) ? value.toString() : (value as string)
                }
            }
            return Promise.resolve(ok({ ...input, headers }))
        })
        mockCreateApplyEventRestrictionsStep.mockReturnValue((input: unknown) => Promise.resolve(ok(input)))
        mockCreateParseAndAnonymizeMessageStep.mockReturnValue(
            async (input: { message: Message; headers: Record<string, string> }) => {
                const scrubKey = `${input.headers.session_id}:${input.message.offset}`
                scrubStarts.add(scrubKey)
                await (scrubGates.get(scrubKey) ?? Promise.resolve())
                const parsedMessage: ParsedMessageData = {
                    metadata: {
                        partition: input.message.partition,
                        topic: input.message.topic,
                        rawSize: input.message.size,
                        offset: input.message.offset,
                        timestamp: input.message.timestamp!,
                    },
                    distinct_id: 'user-123',
                    session_id: input.headers.session_id,
                    token: input.headers.token,
                    eventsByWindowId: {},
                    preSerialized: {
                        lines: Buffer.from('["window-1",{}]\n'),
                        events: [],
                        consoleLogCount: 0,
                        consoleWarnCount: 0,
                        consoleErrorCount: 0,
                    },
                    eventsRange: { start: now, end: now },
                    snapshot_source: null,
                    snapshot_library: null,
                }
                return ok({ ...input, parsedMessage })
            }
        )
    })

    function buildPipeline(): ReturnType<typeof createMlMirrorReplayPipeline> {
        return createMlMirrorReplayPipeline(
            {
                outputs: createMockIngestionOutputs(),
                eventIngestionRestrictionManager: {} as unknown as EventIngestionRestrictionManager,
                overflowMode: 'disabled',
                promiseScheduler,
                teamService,
                retentionService,
                sessionTracker,
                sessionFilter,
                keyStore,
                sessionKeyResolutionMaxConcurrency: 20,
                topHog: {
                    registerSum: jest.fn().mockReturnValue({ record: jest.fn() }),
                    registerMax: jest.fn().mockReturnValue({ record: jest.fn() }),
                    registerAverage: jest.fn().mockReturnValue({ record: jest.fn() }),
                } as unknown as TopHogRegistry,
                isDebugLoggingEnabled: () => false,
            },
            { anonymizeMaxConcurrency: 2 }
        )
    }

    function message(sessionId: string, offset: number): Message {
        return {
            partition: 0,
            offset,
            topic: 'test-topic',
            value: Buffer.from('irrelevant, the scrub step is mocked'),
            key: Buffer.from('k'),
            timestamp: Date.now(),
            headers: [
                { token: Buffer.from('test-token') },
                { session_id: Buffer.from(sessionId) },
                { distinct_id: Buffer.from('user-123') },
            ],
            size: 10,
        } as unknown as Message
    }

    function recordedOffsets(sessionId: string): number[] {
        return recordMock.mock.calls
            .filter((call) => call[0].message.session_id === sessionId)
            .map((call) => call[0].message.metadata.offset)
    }

    async function until(condition: () => boolean): Promise<void> {
        for (let i = 0; i < 5000 && !condition(); i++) {
            await new Promise(setImmediate)
        }
        if (!condition()) {
            throw new Error('condition not reached while a scrub gate was held')
        }
    }

    it('scrubs messages concurrently, including messages of the same session', async () => {
        let releaseFirstScrub!: () => void
        let releaseSecondScrub!: () => void
        scrubGates.set('sess-a:1', new Promise<void>((resolve) => (releaseFirstScrub = resolve)))
        scrubGates.set('sess-a:2', new Promise<void>((resolve) => (releaseSecondScrub = resolve)))

        const recorder = {
            record: recordMock,
            getRetention: jest.fn().mockReturnValue(undefined),
        } as unknown as SessionBatchRecorder
        const run = runSessionReplayPipeline(
            buildPipeline(),
            [message('sess-a', 1), message('sess-a', 2), message('sess-b', 3)],
            recorder,
            promiseScheduler
        )

        try {
            // Both of sess-a's scrubs are in flight at once — sequential processing never starts
            // the second scrub while the first is gated, and per-session grouping never starts a
            // session's second message while its first is gated.
            await until(() => scrubStarts.has('sess-a:1') && scrubStarts.has('sess-a:2'))
        } finally {
            releaseFirstScrub()
            releaseSecondScrub()
        }
        await run

        // No ordering guarantees, so only membership is asserted.
        expect(recordedOffsets('sess-a').sort()).toEqual([1, 2])
        expect(recordedOffsets('sess-b')).toEqual([3])
    })
})
