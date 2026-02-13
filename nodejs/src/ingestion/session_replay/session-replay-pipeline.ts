import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { KafkaMessageParser } from '../../session-recording/kafka/message-parser'
import { ParsedMessageData } from '../../session-recording/kafka/types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '../event-preprocessing'
import { BatchPipelineUnwrapper } from '../pipelines/batch-pipeline-unwrapper'
import { newBatchPipelineBuilder } from '../pipelines/builders'
import { createBatch, createUnwrapper } from '../pipelines/helpers'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { createParseMessageStep } from './parse-message-step'

export interface SessionReplayPipelineInput {
    message: Message
}

export interface SessionReplayPipelineConfig {
    // Message parsing
    parser: KafkaMessageParser

    // Restrictions
    kafkaProducer: KafkaProducerWrapper
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    overflowTopic: string
    promiseScheduler: PromiseScheduler
}

/**
 * Creates the session replay preprocessing pipeline.
 *
 * The pipeline processes messages through these phases:
 * 1. Restrictions - Parse headers and apply event ingestion restrictions (drop/overflow)
 * 2. Parse - Parse Kafka messages into structured session recording data
 *
 * The pipeline will be extended in future commits to include team filtering,
 * version monitoring, and session recording.
 */
export function createSessionReplayPipeline(
    config: SessionReplayPipelineConfig
): BatchPipelineUnwrapper<SessionReplayPipelineInput, ParsedMessageData, { message: Message }> {
    const {
        parser,
        kafkaProducer,
        eventIngestionRestrictionManager,
        overflowEnabled,
        overflowTopic,
        promiseScheduler,
    } = config

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic: '', // Session recordings don't use DLQ for restrictions
        promiseScheduler,
    }

    const pipeline = newBatchPipelineBuilder<SessionReplayPipelineInput, { message: Message }>()
        .messageAware((b) =>
            b
                // Phase 1: Restrictions (parse headers, apply restrictions)
                .sequentially((b) =>
                    b.pipe(createParseHeadersStep()).pipe(
                        createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                            overflowEnabled,
                            overflowTopic,
                            preservePartitionLocality: true, // Sessions must stay on the same partition
                        })
                    )
                )
                // Phase 2: Parse messages
                .pipeBatch(createParseMessageStep(parser))
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
    pipeline: BatchPipelineUnwrapper<SessionReplayPipelineInput, ParsedMessageData, { message: Message }>,
    messages: Message[]
): Promise<ParsedMessageData[]> {
    if (messages.length === 0) {
        return []
    }

    const batch = createBatch(messages.map((message) => ({ message })))
    pipeline.feed(batch)

    const allResults: ParsedMessageData[] = []
    let results = await pipeline.next()
    while (results !== null) {
        allResults.push(...results)
        results = await pipeline.next()
    }

    return allResults
}
