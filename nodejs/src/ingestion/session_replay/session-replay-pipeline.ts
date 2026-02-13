import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '../event-preprocessing'
import { BatchPipelineUnwrapper } from '../pipelines/batch-pipeline-unwrapper'
import { newBatchPipelineBuilder } from '../pipelines/builders'
import { createBatch, createUnwrapper } from '../pipelines/helpers'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'

export interface SessionReplayPipelineInput {
    message: Message
}

export interface SessionReplayPipelineOutput {
    message: Message
    headers: EventHeaders
}

export interface SessionReplayPipelineConfig {
    kafkaProducer?: KafkaProducerWrapper
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    overflowTopic: string
    promiseScheduler: PromiseScheduler
}

/**
 * Creates the session replay preprocessing pipeline.
 *
 * Currently handles restrictions (parsing headers and applying event ingestion
 * restrictions like drop/overflow). The pipeline will be extended in future
 * commits to include additional processing steps.
 */
export function createSessionReplayPipeline(
    config: SessionReplayPipelineConfig
): BatchPipelineUnwrapper<SessionReplayPipelineInput, SessionReplayPipelineOutput, { message: Message }> {
    const { kafkaProducer, eventIngestionRestrictionManager, overflowEnabled, overflowTopic, promiseScheduler } = config

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic: '', // Session recordings don't use DLQ for restrictions
        promiseScheduler,
    }

    const pipeline = newBatchPipelineBuilder<SessionReplayPipelineInput, { message: Message }>()
        .messageAware((b) =>
            b.sequentially((b) =>
                b.pipe(createParseHeadersStep()).pipe(
                    createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                        overflowEnabled,
                        overflowTopic,
                        preservePartitionLocality: true, // Sessions must stay on the same partition
                    })
                )
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
 * Returns only the messages that passed all pipeline checks.
 */
export async function runSessionReplayPipeline(
    pipeline: BatchPipelineUnwrapper<SessionReplayPipelineInput, SessionReplayPipelineOutput, { message: Message }>,
    messages: Message[]
): Promise<Message[]> {
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

    return allResults.map((result) => result.message)
}
