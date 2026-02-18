import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { ParsedMessageData } from '../../session-recording/kafka/types'
import { TeamForReplay } from '../../session-recording/teams/types'
import { TopTracker } from '../../session-recording/top-tracker'
import { TeamService } from '../../session-replay/shared/teams/team-service'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '../event-preprocessing'
import { BatchPipelineUnwrapper } from '../pipelines/batch-pipeline-unwrapper'
import { newBatchPipelineBuilder } from '../pipelines/builders'
import { createBatch, createUnwrapper } from '../pipelines/helpers'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { createParseMessageStep } from './parse-message-step'
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
    promiseScheduler: PromiseScheduler
    teamService: TeamService
    topTracker?: TopTracker
}

/**
 * Creates the session replay preprocessing pipeline.
 *
 * The pipeline processes messages through these phases:
 * 1. Restrictions - Parse headers and apply event ingestion restrictions (drop/overflow)
 * 2. Parse - Parse Kafka messages into structured session recording data
 * 3. Team Filter - Validate team ownership and enrich with team context
 *
 * The pipeline will be extended in future commits to include version monitoring
 * and session recording.
 */
export function createSessionReplayPipeline(
    config: SessionReplayPipelineConfig
): BatchPipelineUnwrapper<SessionReplayPipelineInput, SessionReplayPipelineOutput, { message: Message }> {
    const {
        kafkaProducer,
        eventIngestionRestrictionManager,
        overflowEnabled,
        overflowTopic,
        promiseScheduler,
        teamService,
        topTracker,
    } = config

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic: '', // Session recordings don't use DLQ for restrictions
        promiseScheduler,
    }

    const pipeline = newBatchPipelineBuilder<SessionReplayPipelineInput, { message: Message }>()
        .messageAware((b) =>
            b.sequentially((b) =>
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
                    // Parse message content
                    .pipe(createParseMessageStep({ topTracker }))
                    // Validate team ownership and enrich with team context
                    .pipe(createTeamFilterStep(teamService))
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
