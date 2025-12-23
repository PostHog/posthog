/**
 * Analytics worker for multi-threaded ingestion pipeline.
 *
 * Uses the same groupBy/concurrently/sequentially pattern as the joined pipeline:
 * - Groups events by token:distinctId
 * - Processes groups concurrently
 * - Processes events within each group sequentially
 *
 * The worker maintains a long-lived pipeline and continuously:
 * 1. Receives events via MessagePort
 * 2. Feeds them to the pipeline
 * 3. Calls next() to get results
 * 4. Sends results back via MessagePort
 */
import { MessagePort, workerData } from 'worker_threads'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { Hub, PipelineEvent, Team } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import type { EventPipelineRunnerOptions } from '../../worker/ingestion/event-pipeline/runner'
import type { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import type { BatchPipeline } from '../pipelines/batch-pipeline.interface'
import {
    MainToWorkerMessage,
    WorkerResult,
    WorkerResultType,
    WorkerToMainMessage,
} from '../pipelines/multithreaded/serializable'
import type { WorkerWarning } from '../pipelines/multithreaded/serializable'
import type { PipelineWarning } from '../pipelines/pipeline.interface'
import type { PipelineResult } from '../pipelines/results'
import type { PerEventProcessingConfig, PerEventProcessingInput } from './per-event-processing-subpipeline'
import type { SerializedPerEventInput } from './serializable-per-event-input'

/**
 * Configuration passed to the worker on initialization.
 */
export interface AnalyticsWorkerConfig {
    kafkaConfig: {
        KAFKA_HOSTS: string
        KAFKA_SECURITY_PROTOCOL: string | null
        KAFKA_CLIENT_RACK: string | null
    }

    perEventOptions: EventPipelineRunnerOptions & {
        CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: string
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }

    groupId: string

    // Absolute path to MMDB file (workers have different cwd)
    mmdbFilePath?: string
}

interface WorkerPipelineInput extends PerEventProcessingInput {
    correlationId: string
}

interface WorkerPipelineContext {
    correlationId: string
    sideEffects: Promise<unknown>[]
    warnings: PipelineWarning[]
}

const { config, port } = workerData as { config: AnalyticsWorkerConfig; port: MessagePort }

// Worker-local services (initialized once)
let hub: Hub
let kafkaProducer: KafkaProducerWrapper
let personsStore: any
let groupStore: any
let hogTransformer: any
let pipeline: BatchPipeline<WorkerPipelineInput, void, WorkerPipelineContext, WorkerPipelineContext>

let initialized = false
let initPromise: Promise<void> | null = null
let _processingLoop: Promise<void> | null = null
let flushResolve: (() => void) | null = null
let pendingCount = 0

async function initialize(): Promise<void> {
    if (initialized) {
        return
    }
    if (initPromise) {
        await initPromise
        return
    }

    initPromise = (async () => {
        const { createHub } = await import('../../utils/db/hub')
        const { HogTransformerService } = await import('../../cdp/hog-transformations/hog-transformer.service')
        const { BatchWritingPersonsStore } = await import('../../worker/ingestion/persons/batch-writing-person-store')
        const { BatchWritingGroupStore } = await import('../../worker/ingestion/groups/batch-writing-group-store')
        const { newBatchPipelineBuilder } = await import('../pipelines/builders')
        const { createPerEventProcessingSubpipeline } = await import('./per-event-processing-subpipeline')

        hub = await createHub({
            KAFKA_HOSTS: config.kafkaConfig.KAFKA_HOSTS,
            KAFKA_SECURITY_PROTOCOL: config.kafkaConfig.KAFKA_SECURITY_PROTOCOL as any,
            KAFKA_CLIENT_RACK: config.kafkaConfig.KAFKA_CLIENT_RACK ?? undefined,
            MMDB_FILE_LOCATION: config.mmdbFilePath,
        })

        kafkaProducer = hub.kafkaProducer

        personsStore = new BatchWritingPersonsStore(hub.personRepository, kafkaProducer, {
            dbWriteMode: hub.PERSON_BATCH_WRITING_DB_WRITE_MODE,
            maxConcurrentUpdates: hub.PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: hub.PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: hub.PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
            updateAllProperties: hub.PERSON_PROPERTIES_UPDATE_ALL,
        })

        groupStore = new BatchWritingGroupStore(hub, {
            maxConcurrentUpdates: hub.GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: hub.GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: hub.GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
        })

        hogTransformer = new HogTransformerService(hub)
        await hogTransformer.start()

        const perEventConfig: PerEventProcessingConfig = {
            options: config.perEventOptions,
            teamManager: hub.teamManager,
            groupTypeManager: hub.groupTypeManager,
            hogTransformer,
            personsStore,
            kafkaProducer,
            groupId: config.groupId,
        }

        // Create the pipeline with groupBy/concurrently/sequentially pattern
        // Same structure as joined-ingestion-pipeline
        pipeline = newBatchPipelineBuilder<WorkerPipelineInput, WorkerPipelineContext>()
            .groupBy((input: WorkerPipelineInput) => `${input.event.token ?? ''}:${input.event.distinct_id ?? ''}`)
            .concurrently((eventsForDistinctId) =>
                eventsForDistinctId.sequentially((event) => createPerEventProcessingSubpipeline(event, perEventConfig))
            )
            .gather()
            .build()

        initialized = true

        // Start the processing loop
        _processingLoop = runProcessingLoop()
    })()

    await initPromise
}

/**
 * Continuously call next() on the pipeline and send results back.
 */
async function runProcessingLoop(): Promise<void> {
    while (true) {
        try {
            const results = await pipeline.next()

            if (results === null) {
                // Pipeline is empty, wait a bit before checking again
                await new Promise((resolve) => setTimeout(resolve, 1))
                continue
            }

            for (const item of results) {
                pendingCount--
                const workerResult = mapPipelineResultToWorkerResult(
                    item.result,
                    item.context.correlationId,
                    item.context.warnings
                )
                port.postMessage({ type: 'result', result: workerResult } satisfies WorkerToMainMessage)
            }

            // Check if flush was requested and all events are processed
            if (flushResolve && pendingCount === 0) {
                await personsStore.flush()
                await kafkaProducer.flush()
                flushResolve()
                flushResolve = null
            }
        } catch (error) {
            console.error('[Worker] Processing loop error:', error)
            // Continue the loop even if there's an error
        }
    }
}

function mapPipelineResultToWorkerResult(
    result: PipelineResult<void>,
    correlationId: string,
    contextWarnings: WorkerWarning[]
): WorkerResult {
    const allWarnings = [...(result.warnings || []), ...contextWarnings]

    switch (result.type) {
        case 0: // OK
            return {
                type: WorkerResultType.OK,
                correlationId,
                value: new Uint8Array(0),
                warnings: allWarnings,
            }
        case 1: // DLQ
            return {
                type: WorkerResultType.DLQ,
                correlationId,
                reason: (result as any).reason,
                error: (result as any).error?.toString(),
                warnings: allWarnings,
            }
        case 2: // DROP
            return {
                type: WorkerResultType.DROP,
                correlationId,
                reason: (result as any).reason,
                warnings: allWarnings,
            }
        case 3: // REDIRECT
            return {
                type: WorkerResultType.REDIRECT,
                correlationId,
                reason: (result as any).reason,
                topic: (result as any).topic,
                preserveKey: (result as any).preserveKey,
                awaitAck: (result as any).awaitAck,
                warnings: allWarnings,
            }
        default:
            return {
                type: WorkerResultType.DLQ,
                correlationId,
                reason: 'Unknown result type',
                warnings: allWarnings,
            }
    }
}

port.on('message', (msg: MainToWorkerMessage) => {
    switch (msg.type) {
        case 'event': {
            const serialized = parseJSON(new TextDecoder().decode(msg.data)) as SerializedPerEventInput
            const groupStoreForBatch: GroupStoreForBatch = groupStore.forBatch()

            const input: WorkerPipelineInput = {
                event: serialized.event as PipelineEvent,
                team: serialized.team as Team,
                headers: serialized.headers,
                groupStoreForBatch,
                message: {} as any, // Not needed in worker
                correlationId: msg.correlationId,
            }

            void (async () => {
                await initialize()
                pendingCount++
                const { ok } = await import('../pipelines/results')
                pipeline.feed([
                    {
                        result: ok(input),
                        context: {
                            correlationId: msg.correlationId,
                            sideEffects: [],
                            warnings: [],
                        },
                    },
                ])
            })()
            break
        }
        case 'flush': {
            if (pendingCount === 0) {
                void (async () => {
                    await personsStore?.flush()
                    await kafkaProducer?.flush()
                    port.postMessage({ type: 'flush_complete' } satisfies WorkerToMainMessage)
                })()
            } else {
                // Wait for all pending events to complete
                void new Promise<void>((resolve) => {
                    flushResolve = resolve
                }).then(() => {
                    port.postMessage({ type: 'flush_complete' } satisfies WorkerToMainMessage)
                })
            }
            break
        }
        case 'shutdown': {
            void (async () => {
                try {
                    await personsStore?.flush()
                    await kafkaProducer?.flush()
                    await kafkaProducer?.disconnect()
                    if (hub?.postgres) {
                        await hub.postgres.end()
                    }
                } catch {
                    // Ignore cleanup errors
                }
                process.exit(0)
            })()
            break
        }
    }
})

// Signal ready to receive events
port.postMessage({ type: 'ready' } satisfies WorkerToMainMessage)
