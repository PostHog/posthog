import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { ParsedMessageData } from '../../session-recording/kafka/types'
import { SessionBatchManager } from '../../session-recording/sessions/session-batch-manager'
import { TeamForReplay } from '../../session-recording/teams/types'
import { TeamService } from '../../session-replay/shared/teams/team-service'
import { ValueMatcher } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '../event-preprocessing'
import { BatchPipelineUnwrapper } from '../pipelines/batch-pipeline-unwrapper'
import { newBatchPipelineBuilder } from '../pipelines/builders'
import { TopHogRegistry, createTopHogWrapper, sum, timer } from '../pipelines/extensions/tophog'
import { createBatch, createUnwrapper } from '../pipelines/helpers'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { createLibVersionMonitorStep } from './lib-version-monitor-step'
import { createParseMessageStep } from './parse-message-step'
import { createRecordSessionEventStep } from './record-session-event-step'
import { createTeamFilterStep } from './team-filter-step'

export interface SessionReplayPipelineInput {
    message: Message
}

export interface SessionReplayPipelineOutput {
    team: TeamForReplay
    parsedMessage: ParsedMessageData
}

export interface SessionReplayPipelineConfig {
    kafkaProducer: KafkaProducerWrapper
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    overflowTopic: string
    dlqTopic: string
    promiseScheduler: PromiseScheduler
    teamService: TeamService
    /** TopHog registry for tracking metrics. */
    topHog: TopHogRegistry
    /** Producer for ingestion warnings. */
    ingestionWarningProducer: KafkaProducerWrapper
    /** Session batch manager for recording sessions. */
    sessionBatchManager: SessionBatchManager
    /** Debug logging matcher for partition-based debugging. */
    isDebugLoggingEnabled: ValueMatcher<number>
}

/**
 * Creates the session replay pipeline.
 *
 * The pipeline processes messages through these phases:
 * 1. Restrictions - Parse headers and apply event ingestion restrictions (drop/overflow)
 * 2. Team Filter - Validate team ownership and enrich with team context
 * 3. Parse - Parse Kafka messages into structured session recording data (inside teamAware for warning handling)
 * 4. Version Monitor - Check library version and emit warnings for old versions
 * 5. Record - Record parsed messages to session batches
 */
export function createSessionReplayPipeline(
    config: SessionReplayPipelineConfig
): BatchPipelineUnwrapper<SessionReplayPipelineInput, SessionReplayPipelineOutput, { message: Message }> {
    const {
        kafkaProducer,
        eventIngestionRestrictionManager,
        overflowEnabled,
        overflowTopic,
        dlqTopic,
        promiseScheduler,
        teamService,
        topHog,
        ingestionWarningProducer,
        sessionBatchManager,
        isDebugLoggingEnabled,
    } = config

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic,
        promiseScheduler,
    }

    const topHogWrapper = createTopHogWrapper(topHog)

    const pipeline = newBatchPipelineBuilder<SessionReplayPipelineInput, { message: Message }>()
        .messageAware((b) =>
            b
                .sequentially((b) =>
                    b
                        // Parse headers and apply restrictions (drop/overflow)
                        .pipe(createParseHeadersStep())
                        .pipe(
                            createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                                overflowEnabled,
                                overflowTopic,
                                preservePartitionLocality: true, // Sessions must stay on the same partition
                            })
                        )
                        // Validate team ownership and enrich with team context
                        .pipe(createTeamFilterStep(teamService))
                )
                // Map TeamForReplay.teamId to context.team.id for handleIngestionWarnings
                .filterMap(
                    (element) => ({
                        result: element.result,
                        context: {
                            ...element.context,
                            team: { id: element.result.value.team.teamId },
                        },
                    }),
                    (b) =>
                        b
                            .teamAware((b) =>
                                b
                                    .sequentially((b) =>
                                        b
                                            // Parse message content
                                            .pipe(
                                                topHogWrapper(createParseMessageStep(), [
                                                    timer('parse_time_ms_by_session_id', (input) => ({
                                                        token: input.headers.token ?? 'unknown',
                                                        session_id: input.headers.session_id ?? 'unknown',
                                                    })),
                                                ])
                                            )
                                            // Monitor library version and emit warnings for old versions
                                            .pipe(createLibVersionMonitorStep())
                                            // Record to session batch
                                            .pipe(
                                                topHogWrapper(
                                                    createRecordSessionEventStep({
                                                        sessionBatchManager,
                                                        isDebugLoggingEnabled,
                                                    }),
                                                    [
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
                                                    ]
                                                )
                                            )
                                    )
                                    .gather()
                            )
                            .handleIngestionWarnings(ingestionWarningProducer)
                )
        )
        .handleResults(pipelineConfig)
        .handleSideEffects(promiseScheduler, { await: false })
        .gather()
        .build()

    return createUnwrapper(pipeline)
}

/**
 * Runs a batch of messages through the session replay pipeline.
 *
 * Returns parsed messages for the existing team filtering/processing flow to continue.
 * In future commits, the pipeline will handle all processing internally.
 */
export async function runSessionReplayPipeline(
    pipeline: BatchPipelineUnwrapper<SessionReplayPipelineInput, SessionReplayPipelineOutput, { message: Message }>,
    messages: Message[]
): Promise<SessionReplayPipelineOutput[]> {
    if (messages.length === 0) {
        return []
    }

    const batch = createBatch(messages.map((message) => ({ message })))
    pipeline.feed(batch)

    const allResults: SessionReplayPipelineOutput[] = []
    let results = await pipeline.next()
    while (results !== null) {
        allResults.push(...results)
        results = await pipeline.next()
    }

    return allResults
}
