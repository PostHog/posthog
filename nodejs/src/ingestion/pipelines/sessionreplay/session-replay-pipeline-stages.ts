import { OverflowOutput } from '~/common/outputs'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { ChunkPipelineBuilder, PipelineBuilder, StartPipelineBuilder } from '~/ingestion/framework/builders'
import { TopHogRegistry, createTopHogWrapper, sum, timer } from '~/ingestion/framework/extensions/tophog'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { NewSessionFlag, Recordable, SessionReplayHeaders } from './pipeline-types'
import { RecordSessionEventStepInput } from './record-session-event-step'
import { createMarkSeenStep } from './session-batch-mark-seen-step'
import { createResolveRetentionStep } from './session-batch-resolve-retention-step'
import { createTrackAndGateStep } from './session-batch-track-and-gate-step'
import type { SessionReplayPipelineConfig, SessionReplayPipelineInput } from './session-replay-pipeline'
import { createResolveKeyStep } from './session-resolve-key-step'
import { RetentionPeriod } from './shared/constants'
import { RetentionService } from './shared/retention/retention-service'
import { createTeamFilterStep } from './team-filter-step'
import { TeamForReplay } from './teams/types'
import { createValidateSessionReplayHeadersStep } from './validate-headers-step'

type ValidatedReplayInput = SessionReplayPipelineInput & { headers: SessionReplayHeaders; team: TeamForReplay }

export function addSessionReplayPreprocessing<C>(
    builder: StartPipelineBuilder<SessionReplayPipelineInput, C>,
    config: Pick<SessionReplayPipelineConfig, 'eventIngestionRestrictionManager' | 'overflowMode' | 'teamService'>
): PipelineBuilder<SessionReplayPipelineInput, ValidatedReplayInput, C, OverflowOutput> {
    const { eventIngestionRestrictionManager, overflowMode, teamService } = config
    return (
        builder
            // Parse headers and apply restrictions (drop/overflow)
            .pipe(createParseHeadersStep())
            .pipe(
                createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                    overflowMode,
                    preservePartitionLocality: true, // Sessions must stay on the same partition
                    // Replay never reads or writes persons. The line above pins
                    // locality either way, so this only records the fact.
                    pipelineWritesPersons: false,
                })
            )
            // Validate the headers capture guarantees (DLQ if missing) and narrow the type
            .pipe(createValidateSessionReplayHeadersStep())
            // Validate team ownership and enrich with team context
            .pipe(createTeamFilterStep(teamService))
    )
}

type SessionResolutionConfig = Pick<
    SessionReplayPipelineConfig,
    'sessionTracker' | 'sessionFilter' | 'keyStore' | 'sessionKeyResolutionMaxConcurrency'
>

/** Resolves each session's retention, tracks and rate-limits sessions, and resolves their keys. */
export function addSessionReplaySessionResolution<
    TInput,
    T extends ValidatedReplayInput,
    CInput,
    COutput,
    R extends string,
    D,
>(
    builder: ChunkPipelineBuilder<TInput, T, CInput, COutput, R, D>,
    config: SessionResolutionConfig & { retentionService: RetentionService }
): ChunkPipelineBuilder<
    TInput,
    Recordable<T & { retentionPeriod: RetentionPeriod } & NewSessionFlag>,
    CInput,
    COutput,
    R,
    D
>
/** The same without the retention lookup, for a lane whose storage and keys do not depend on retention. Its elements carry a null retention, which the sinks that need one refuse. */
export function addSessionReplaySessionResolution<
    TInput,
    T extends ValidatedReplayInput,
    CInput,
    COutput,
    R extends string,
    D,
>(
    builder: ChunkPipelineBuilder<TInput, T, CInput, COutput, R, D>,
    config: SessionResolutionConfig,
    options: { resolveRetention: false }
): ChunkPipelineBuilder<TInput, Recordable<T & { retentionPeriod: null } & NewSessionFlag>, CInput, COutput, R, D>
export function addSessionReplaySessionResolution<
    TInput,
    T extends ValidatedReplayInput,
    CInput,
    COutput,
    R extends string,
    D,
>(
    builder: ChunkPipelineBuilder<TInput, T, CInput, COutput, R, D>,
    config: SessionResolutionConfig & { retentionService?: RetentionService },
    options?: { resolveRetention: false }
): ChunkPipelineBuilder<
    TInput,
    Recordable<T & { retentionPeriod: RetentionPeriod | null } & NewSessionFlag>,
    CInput,
    COutput,
    R,
    D
> {
    const { retentionService, sessionTracker, sessionFilter, keyStore, sessionKeyResolutionMaxConcurrency } = config
    const withRetention: ChunkPipelineBuilder<
        TInput,
        T & { retentionPeriod: RetentionPeriod | null },
        CInput,
        COutput,
        R,
        D
    > =
        options?.resolveRetention === false || !retentionService
            ? builder.pipeChunk(function skipRetention(values) {
                  return Promise.resolve(values.map((value) => ok({ ...value, retentionPeriod: null })))
              })
            : builder.pipeChunk(createResolveRetentionStep(retentionService), {
                  retry: { tries: 3, sleepMs: 100 },
              })
    return (
        withRetention
            // Track sessions and rate-limit new ones for the whole batch, tagging the survivors with
            // isNewSession and dropping the blocked ones right here (they carry no key, so nothing
            // downstream acts on them). Its own retry scope means a later key-resolution failure never
            // re-runs the rate limiter and double-charges the budget.
            .pipeChunk(createTrackAndGateStep(sessionTracker, sessionFilter), {
                retry: { tries: 3, sleepMs: 100 },
            })
            // Resolve each session's encryption key. Grouped by session so it runs once per session
            // (the cached keystore fans the key to its other messages) and concurrently across
            // sessions, capped to bound KMS/DynamoDB fan-out. Per-session retry isolates a transient
            // keystore blip to that one session. Deleted sessions are dropped here.
            .concurrentlyPerGroup(
                (element) => `${element.team.teamId}:${element.headers.session_id}`,
                (group) =>
                    group.sequentially((b) =>
                        b.pipe(createResolveKeyStep(keyStore), {
                            retry: { name: 'resolve_session_key', tries: 3, sleepMs: 100 },
                        })
                    ),
                { maxConcurrency: sessionKeyResolutionMaxConcurrency }
            )
            // Re-collect the per-session groups into one batch — both to mark the whole batch seen
            // in a single Redis write and as the barrier that guarantees every key is resolved first.
            .gather()
            // Mark the surviving new sessions seen, now that every key is durably resolved.
            .pipeChunk(createMarkSeenStep(sessionTracker))
    )
}

export function withSessionReplayRecordingMetrics<T extends RecordSessionEventStepInput>(
    topHog: TopHogRegistry,
    step: ProcessingStep<T, T>
): ProcessingStep<T, T> {
    return createTopHogWrapper(topHog)(step, [
        sum(
            'message_size_by_session_id',
            (input) => ({
                token: input.parsedMessage.token ?? 'unknown',
                session_id: input.parsedMessage.session_id,
            }),
            (input) => input.parsedMessage.metadata.rawSize
        ),
        timer('consume_time_ms_by_session_id', (input) => ({
            token: input.parsedMessage.token ?? 'unknown',
            session_id: input.parsedMessage.session_id,
        })),
    ])
}
