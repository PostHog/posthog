/**
 * Worker thread entry point for multithreaded batch processing.
 *
 * Each worker:
 * - Receives serialized events via MessagePort
 * - Deserializes and groups them internally
 * - Processes them through an internal ConcurrentlyGroupingBatchPipeline
 * - Handles side effects internally (has own connections)
 * - Returns results (OK/DLQ/DROP/REDIRECT) without sideEffects
 */
import { MessagePort, workerData } from 'worker_threads'

import { BatchPipeline } from '../batch-pipeline.interface'
import { PipelineContext, PipelineResultWithContext } from '../pipeline.interface'
import { PipelineResult, PipelineResultType, ok } from '../results'
import { Deserializer, MainToWorkerMessage, WorkerResult, WorkerResultType, WorkerToMainMessage } from './serializable'

export interface WorkerConfig<TInput, TOutput> {
    /**
     * Factory function to create the internal pipeline.
     * Called once when worker initializes.
     */
    createPipeline: () => Promise<BatchPipeline<TInput, TOutput, WorkerEventContext, WorkerEventContext>>

    /**
     * Deserializer for converting incoming Uint8Array to pipeline input.
     */
    deserializer: Deserializer<TInput>

    /**
     * Function to extract group key from input for internal grouping.
     */
    getGroupKey: (input: TInput) => string

    /**
     * Optional serializer for OK result values.
     * If not provided, returns empty Uint8Array for OK results.
     */
    serializeOutput?: (output: TOutput) => Uint8Array
}

export interface WorkerEventContext {
    correlationId: string
}

interface PendingEvent<TInput> {
    correlationId: string
    input: TInput
}

const { config, port } = workerData as { config: WorkerConfig<unknown, unknown>; port: MessagePort }

let pipeline: BatchPipeline<unknown, unknown, WorkerEventContext, WorkerEventContext>
let initialized = false
let initializing = false
let initPromise: Promise<void> | null = null

const eventBuffer: PendingEvent<unknown>[] = []
let processing = false
let flushRequested = false

async function initialize(): Promise<void> {
    if (initialized) {
        return
    }
    if (initializing && initPromise) {
        await initPromise
        return
    }

    initializing = true
    initPromise = (async () => {
        pipeline = await config.createPipeline()
        initialized = true
        port.postMessage({ type: 'ready' } satisfies WorkerToMainMessage)
    })()

    await initPromise
}

async function processBuffer(): Promise<void> {
    if (processing || eventBuffer.length === 0) {
        return
    }
    processing = true

    try {
        // Take current batch
        const batch = eventBuffer.splice(0, eventBuffer.length)

        // Feed to internal pipeline
        pipeline.feed(
            batch.map((e) => ({
                result: ok(e.input),
                context: {
                    correlationId: e.correlationId,
                    sideEffects: [],
                    warnings: [],
                } as PipelineContext<WorkerEventContext>,
            }))
        )

        // Process and send results back
        let result: PipelineResultWithContext<unknown, WorkerEventContext>[] | null
        while ((result = await pipeline.next()) !== null) {
            for (const item of result) {
                const workerResult = mapPipelineResultToWorkerResult(item.result, item.context.correlationId)
                port.postMessage({ type: 'result', result: workerResult } satisfies WorkerToMainMessage)
            }
        }
    } finally {
        processing = false
    }

    // Process any events that arrived while we were processing
    if (eventBuffer.length > 0) {
        setImmediate(() => processBuffer())
    } else if (flushRequested) {
        flushRequested = false
        port.postMessage({ type: 'flush_complete' } satisfies WorkerToMainMessage)
    }
}

function mapPipelineResultToWorkerResult(result: PipelineResult<unknown>, correlationId: string): WorkerResult {
    switch (result.type) {
        case PipelineResultType.OK:
            return {
                type: WorkerResultType.OK,
                correlationId,
                value: config.serializeOutput?.(result.value) ?? new Uint8Array(0),
                warnings: result.warnings,
            }
        case PipelineResultType.DLQ:
            return {
                type: WorkerResultType.DLQ,
                correlationId,
                reason: result.reason,
                error: result.error?.toString(),
                warnings: result.warnings,
            }
        case PipelineResultType.DROP:
            return {
                type: WorkerResultType.DROP,
                correlationId,
                reason: result.reason,
                warnings: result.warnings,
            }
        case PipelineResultType.REDIRECT:
            return {
                type: WorkerResultType.REDIRECT,
                correlationId,
                reason: result.reason,
                topic: result.topic,
                preserveKey: result.preserveKey,
                awaitAck: result.awaitAck,
                warnings: result.warnings,
            }
    }
}

port.on('message', async (msg: MainToWorkerMessage) => {
    switch (msg.type) {
        case 'event': {
            // Ensure initialized before processing
            await initialize()

            const input = config.deserializer.deserialize(msg.data)
            eventBuffer.push({ correlationId: msg.correlationId, input })
            void processBuffer()
            break
        }
        case 'flush': {
            // Wait for buffer to drain
            if (eventBuffer.length === 0 && !processing) {
                port.postMessage({ type: 'flush_complete' } satisfies WorkerToMainMessage)
            } else {
                flushRequested = true
                // Trigger processing if not already running
                void processBuffer()
            }
            break
        }
        case 'shutdown': {
            process.exit(0)
        }
    }
})

// Keep port referenced to prevent event loop from exiting
port.ref()

// Start initialization immediately
void initialize()
