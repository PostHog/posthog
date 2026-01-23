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

export interface RestrictionPipelineInput {
    message: Message
}

export interface RestrictionPipelineOutput {
    message: Message
    headers: EventHeaders
}

export interface RestrictionPipelineConfig {
    kafkaProducer: KafkaProducerWrapper
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    overflowTopic: string
    promiseScheduler: PromiseScheduler
}

export function createRestrictionPipeline(
    config: RestrictionPipelineConfig
): BatchPipelineUnwrapper<RestrictionPipelineInput, RestrictionPipelineOutput, { message: Message }> {
    const { kafkaProducer, eventIngestionRestrictionManager, overflowEnabled, overflowTopic, promiseScheduler } = config

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic: '', // Session recordings don't use DLQ for restrictions
        promiseScheduler,
    }

    const pipeline = newBatchPipelineBuilder<RestrictionPipelineInput, { message: Message }>()
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
 * Apply restrictions to a batch of messages using the pipeline.
 * Returns only the messages that passed restriction checks.
 */
export async function applyRestrictions(
    pipeline: BatchPipelineUnwrapper<RestrictionPipelineInput, RestrictionPipelineOutput, { message: Message }>,
    messages: Message[]
): Promise<Message[]> {
    if (messages.length === 0) {
        return []
    }

    const batch = createBatch(messages.map((message) => ({ message })))
    pipeline.feed(batch)

    const allResults: RestrictionPipelineOutput[] = []
    let results = await pipeline.next()
    while (results !== null) {
        allResults.push(...results)
        results = await pipeline.next()
    }

    return allResults.map((result) => result.message)
}
