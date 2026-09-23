import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'
import { ok } from '~/ingestion/framework/results'
import { SessionReplayPipelineConfig } from '~/ingestion/pipelines/sessionreplay'
import { BatchStages } from '~/ingestion/pipelines/sessionreplay/batch-stages'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import {
    MlMirrorCollection,
    MlMirrorImageScrubProducer,
    MlMirrorPipelineOptions,
    MlMirrorUrlFetchProducer,
} from '~/ingestion/pipelines/sessionreplay/ml-mirror/ml-mirror-pipeline'
import {
    ML_BATCH_STAGES,
    MlMirrorStagedBatchRunner,
} from '~/ingestion/pipelines/sessionreplay/ml-mirror/staged-batch-runner'
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
import { BatchCommitter } from '~/ingestion/pipelines/sessionreplay/staged-batch'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'

/** Test-only: the runner the ML mirror server builds, started on one pipeline config. */
export function buildMlMirrorStagedRunner(
    config: SessionReplayPipelineConfig,
    mlOptions: MlMirrorPipelineOptions,
    imageScrub?: MlMirrorImageScrubProducer,
    collection?: MlMirrorCollection,
    urlFetch?: MlMirrorUrlFetchProducer
): MlMirrorStagedBatchRunner {
    const runner = new MlMirrorStagedBatchRunner(mlOptions, imageScrub, collection, urlFetch)
    runner.start(config)
    return runner
}

/** Test-only: a committer that records into one fixed recorder and never flushes. */
export function recordingCommitter(recorder: SessionBatchRecorder): BatchCommitter {
    return {
        knownRetention: (teamId, sessionId) => recorder.getRetention(teamId, sessionId),
        commit: async (write) => {
            await write(recorder, () => true)
        },
    }
}

/** Test-only: runs one poll batch to completion against one recorder, admitted to its own stages unless the test shares some. */
export function runMlMirrorBatch(
    runner: MlMirrorStagedBatchRunner,
    messages: Message[],
    recorder: SessionBatchRecorder,
    stages: BatchStages = new BatchStages(ML_BATCH_STAGES)
): Promise<void> {
    return runner.run(messages, stages.admit(), recordingCommitter(recorder))
}

type MlMirrorTestServices = Pick<
    SessionReplayPipelineConfig,
    'retentionService' | 'sessionTracker' | 'sessionFilter' | 'keyStore' | 'teamService'
>

/** Test-only: services that resolve every session to 30 days, already seen, unblocked, with a cleartext key, for team 1 whose consent the token decides. */
export function mlMirrorTestServices(isOptedIn: (token: string) => boolean = () => true): MlMirrorTestServices {
    return {
        retentionService: {
            resolveSessionRetentions: jest.fn().mockImplementation((sessions: SessionSet) => {
                const resolutions = new SessionMap<RetentionResolution>()
                for (const s of sessions) {
                    resolutions.set(s.teamId, s.sessionId, { resolved: true, retentionPeriod: '30d' })
                }
                return Promise.resolve(resolutions)
            }),
        } as unknown as RetentionService,
        sessionTracker: {
            hasSeen: jest.fn().mockImplementation((sessions: SessionSet) => {
                const map = new SessionMap<boolean>()
                for (const { teamId, sessionId } of sessions) {
                    map.set(teamId, sessionId, true)
                }
                return Promise.resolve(map)
            }),
            markSeen: jest.fn().mockResolvedValue(undefined),
        } as unknown as SessionTracker,
        sessionFilter: {
            handleNewSessions: jest.fn().mockResolvedValue(new SessionSet()),
            isBlocked: jest.fn().mockResolvedValue(new SessionSet()),
        } as unknown as SessionFilter,
        keyStore: createMockKeyStore(),
        teamService: {
            getTeamByToken: jest.fn().mockImplementation((token: string) =>
                Promise.resolve({
                    teamId: 1,
                    consoleLogIngestionEnabled: false,
                    aiTrainingOptedIn: isOptedIn(token),
                } satisfies TeamForReplay)
            ),
            getRetentionPeriodByTeamId: jest.fn().mockResolvedValue(30),
        } as unknown as TeamService,
    }
}

/** Test-only: a pipeline config over the test services with mock outputs and TopHog. */
export function mlMirrorTestPipelineConfig(
    promiseScheduler: PromiseScheduler,
    services: MlMirrorTestServices
): SessionReplayPipelineConfig {
    return {
        outputs: createMockIngestionOutputs(),
        eventIngestionRestrictionManager: {} as unknown as EventIngestionRestrictionManager,
        overflowMode: 'disabled',
        promiseScheduler,
        ...services,
        sessionKeyResolutionMaxConcurrency: 20,
        topHog: {
            registerSum: jest.fn().mockReturnValue({ record: jest.fn() }),
            registerMax: jest.fn().mockReturnValue({ record: jest.fn() }),
            registerAverage: jest.fn().mockReturnValue({ record: jest.fn() }),
        } as unknown as TopHogRegistry,
        isDebugLoggingEnabled: () => false,
    }
}

/** Test-only: stands in for the parse-headers step, reading the Kafka headers into a map. */
export function parseTestHeaders<T extends { message: Message }>(
    input: T
): Promise<ReturnType<typeof ok<T & { headers: Record<string, string> }>>> {
    const headers: Record<string, string> = {}
    for (const header of input.message.headers || []) {
        for (const [key, value] of Object.entries(header)) {
            headers[key] = Buffer.isBuffer(value) ? value.toString() : (value as string)
        }
    }
    return Promise.resolve(ok({ ...input, headers }))
}

/** Test-only: what a mocked scrub step hands back for one message, with one empty event line. */
export function scrubbedTestMessage(
    input: { message: Message; headers: Record<string, string> },
    now: DateTime
): ParsedMessageData {
    return {
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
}

/** Test-only: a replay message on partition 0 whose payload the mocked scrub never reads. */
export function mlMirrorTestMessage(sessionId: string, offset: number, token = 'test-token'): Message {
    return {
        partition: 0,
        offset,
        topic: 'test-topic',
        value: Buffer.from('irrelevant, the scrub step is mocked'),
        key: Buffer.from('k'),
        timestamp: Date.now(),
        headers: [
            { token: Buffer.from(token) },
            { session_id: Buffer.from(sessionId) },
            { distinct_id: Buffer.from('user-123') },
        ],
        size: 10,
    } as unknown as Message
}
