import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT, OVERFLOW_OUTPUT } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'
import { ok } from '~/ingestion/framework/results'
import { runSessionReplayPipeline } from '~/ingestion/pipelines/sessionreplay'
import { defaultAllowLists } from '~/ingestion/pipelines/sessionreplay/anonymize/default-dict'
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

import { createMlMirrorReplayPipeline } from './ml-mirror-pipeline'

jest.mock('~/ingestion/common/steps/event-preprocessing', () => ({
    createParseHeadersStep: jest.fn(),
    createApplyEventRestrictionsStep: jest.fn(),
}))

const mockCreateParseHeadersStep = createParseHeadersStep as jest.Mock
const mockCreateApplyEventRestrictionsStep = createApplyEventRestrictionsStep as jest.Mock

// The pipeline's parse+anonymize step runs inside the native addon; scrub-dependent tests need it built.
let rustAddon: typeof import('@posthog/replay-anonymizer') | null = null
try {
    rustAddon = require('@posthog/replay-anonymizer')
    rustAddon!.initAnonymizer(defaultAllowLists().entries())
} catch (e) {
    if (process.env.CI) {
        throw new Error(`replay-anonymizer addon failed to load; pipeline tests cannot run in CI: ${String(e)}`)
    }
    logger.warn('🙈', 'replay_anonymizer_addon_not_built_skipping_pipeline_scrub_tests')
}
const itAddon = rustAddon ? it : it.skip

function createMockTopHog(): TopHogRegistry {
    const recorder = { record: jest.fn() }
    return {
        registerSum: jest.fn().mockReturnValue(recorder),
        registerMax: jest.fn().mockReturnValue(recorder),
        registerAverage: jest.fn().mockReturnValue(recorder),
    } as unknown as TopHogRegistry
}

describe('ml-mirror-pipeline', () => {
    let recordMock: jest.Mock
    let mockSessionBatchManager: jest.Mocked<SessionBatchManager>
    let mockTeamService: TeamService
    let topHog: TopHogRegistry
    let promiseScheduler: PromiseScheduler
    let outputs: jest.Mocked<
        IngestionOutputs<typeof DLQ_OUTPUT | typeof OVERFLOW_OUTPUT | typeof INGESTION_WARNINGS_OUTPUT>
    >

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
    const now = DateTime.now()

    const team = (aiTrainingOptedIn: boolean): TeamForReplay => ({
        teamId: 1,
        consoleLogIngestionEnabled: false,
        aiTrainingOptedIn,
        firstPartyHosts: [],
    })

    beforeEach(() => {
        jest.clearAllMocks()
        outputs = createMockIngestionOutputs()

        recordMock = jest.fn().mockResolvedValue(undefined)
        const recorder = {
            record: recordMock,
            getRetention: jest.fn().mockReturnValue(undefined),
        } as unknown as jest.Mocked<SessionBatchRecorder>
        mockSessionBatchManager = {
            getCurrentBatch: jest.fn().mockReturnValue(recorder),
            shouldFlush: jest.fn().mockReturnValue(false),
            flush: jest.fn().mockResolvedValue(undefined),
            discardPartitions: jest.fn(),
        } as unknown as jest.Mocked<SessionBatchManager>

        topHog = createMockTopHog()
        promiseScheduler = new PromiseScheduler()

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
    })

    function buildPipeline(): ReturnType<typeof createMlMirrorReplayPipeline> {
        return createMlMirrorReplayPipeline({
            outputs,
            eventIngestionRestrictionManager: {} as unknown as EventIngestionRestrictionManager,
            overflowMode: 'disabled',
            promiseScheduler,
            teamService: mockTeamService,
            retentionService,
            sessionTracker,
            sessionFilter,
            keyStore,
            sessionKeyResolutionMaxConcurrency: 20,
            topHog,
            sessionBatchManager: mockSessionBatchManager,
            isDebugLoggingEnabled: () => false,
        })
    }

    function message(sessionId: string): Message {
        const payload = JSON.stringify({
            distinct_id: 'user-123',
            data: JSON.stringify({
                event: '$snapshot_items',
                properties: {
                    $session_id: sessionId,
                    $window_id: 'window-1',
                    $snapshot_items: [
                        {
                            type: 3,
                            timestamp: now.toMillis(),
                            data: { source: 5, id: 1, text: 'Hello SecretName', isChecked: false },
                        },
                    ],
                },
            }),
        })
        return {
            partition: 0,
            offset: 1,
            topic: 'test-topic',
            value: Buffer.from(payload),
            key: Buffer.from('k'),
            timestamp: Date.now(),
            headers: [
                { token: Buffer.from('test-token') },
                { session_id: Buffer.from(sessionId) },
                { distinct_id: Buffer.from('user-123') },
            ],
            size: payload.length,
        } as unknown as Message
    }

    function fullSnapshotMessage(sessionId: string): Message {
        const snapshot = {
            type: 2,
            timestamp: now.toMillis(),
            data: {
                node: {
                    type: 0,
                    id: 1,
                    childNodes: [
                        {
                            type: 2,
                            id: 2,
                            tagName: 'a',
                            attributes: {
                                href: 'https://example.com/u/abc/edit',
                                'data-note': 'Smithson lives nearby',
                            },
                            childNodes: [{ type: 3, id: 3, textContent: 'Hello SecretName' }],
                        },
                    ],
                },
                initialOffset: { top: 0, left: 0 },
            },
        }
        const payload = JSON.stringify({
            distinct_id: 'user-123',
            data: JSON.stringify({
                event: '$snapshot_items',
                properties: { $session_id: sessionId, $window_id: 'window-1', $snapshot_items: [snapshot] },
            }),
        })
        return {
            partition: 0,
            offset: 1,
            topic: 'test-topic',
            value: Buffer.from(payload),
            key: Buffer.from('k'),
            timestamp: Date.now(),
            headers: [
                { token: Buffer.from('test-token') },
                { session_id: Buffer.from(sessionId) },
                { distinct_id: Buffer.from('user-123') },
            ],
            size: payload.length,
        } as unknown as Message
    }

    // The fused step emits pre-serialized JSONL lines of [windowId, event].
    function recordedEvents(): [string, any][] {
        const lines: Buffer = recordMock.mock.calls[0][0].message.preSerialized.lines
        return lines
            .toString()
            .split('\n')
            .filter((l) => l.length > 0)
            .map((l) => parseJSON(l))
    }

    itAddon('anonymizes events before recording for an opted-in team', async () => {
        mockTeamService = {
            getTeamByToken: jest.fn().mockResolvedValue(team(true)),
            getRetentionPeriodByTeamId: jest.fn().mockResolvedValue(30),
        } as unknown as TeamService

        await runSessionReplayPipeline(buildPipeline(), [message('sess-1')])

        expect(recordMock).toHaveBeenCalledTimes(1)
        const [windowId, event] = recordedEvents()[0]
        expect(windowId).toBe('window-1')
        // The Input event's text was scrubbed before it reached the recorder.
        expect(event.data.text).toBe('Hello **********')
    })

    it('drops sessions for a team that did not opt into AI training', async () => {
        mockTeamService = {
            getTeamByToken: jest.fn().mockResolvedValue(team(false)),
            getRetentionPeriodByTeamId: jest.fn().mockResolvedValue(30),
        } as unknown as TeamService

        await runSessionReplayPipeline(buildPipeline(), [message('sess-2')])

        expect(recordMock).not.toHaveBeenCalled()
    })

    itAddon('scrubs a FullSnapshot (text, url, free-text data-*) end-to-end before recording', async () => {
        mockTeamService = {
            getTeamByToken: jest.fn().mockResolvedValue(team(true)),
            getRetentionPeriodByTeamId: jest.fn().mockResolvedValue(30),
        } as unknown as TeamService

        await runSessionReplayPipeline(buildPipeline(), [fullSnapshotMessage('sess-3')])

        expect(recordMock).toHaveBeenCalledTimes(1)
        const node = recordedEvents()[0][1].data.node.childNodes[0]
        expect(node.childNodes[0].textContent).toBe('Hello **********') // DOM text
        expect(node.attributes.href).toContain('https://example.com/') // authority kept...
        expect(node.attributes.href).not.toContain('abc') // ...path segments redacted
        expect(node.attributes['data-note']).not.toContain('Smithson') // free-text data-* scrubbed
    })
})
