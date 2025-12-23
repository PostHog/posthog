/**
 * Test worker that uses a simple pipeline for testing worker.ts functionality.
 * Processes JSON input and returns processed JSON output.
 */
import { MessagePort, workerData } from 'worker_threads'

import { parseJSON } from '../../../utils/json-parse'
import { BatchPipeline, BatchPipelineResultWithContext } from '../batch-pipeline.interface'
import { PipelineContext, PipelineResultWithContext } from '../pipeline.interface'
import { PipelineResult, PipelineResultType, ok } from '../results'
import { MainToWorkerMessage, WorkerResult, WorkerResultType, WorkerToMainMessage } from './serializable'

interface TestInput {
    [key: string]: unknown
}

interface TestOutput {
    processed: true
    original: TestInput
}

interface WorkerEventContext {
    correlationId: string
}

interface PendingEvent {
    correlationId: string
    input: TestInput
}

/**
 * Simple batch pipeline that marks input as processed.
 */
class TestBatchPipeline implements BatchPipeline<TestInput, TestOutput, WorkerEventContext, WorkerEventContext> {
    private buffer: PipelineResultWithContext<TestInput, WorkerEventContext>[] = []

    feed(elements: BatchPipelineResultWithContext<TestInput, WorkerEventContext>): void {
        this.buffer.push(...elements)
    }

    next(): Promise<BatchPipelineResultWithContext<TestOutput, WorkerEventContext> | null> {
        if (this.buffer.length === 0) {
            return Promise.resolve(null)
        }

        const batch = this.buffer.splice(0, this.buffer.length)
        return Promise.resolve(
            batch.map((item) => {
                if (item.result.type === PipelineResultType.OK) {
                    return {
                        result: ok<TestOutput>({
                            processed: true,
                            original: item.result.value,
                        }),
                        context: item.context,
                    }
                }
                return item as PipelineResultWithContext<TestOutput, WorkerEventContext>
            })
        )
    }
}

const { port } = workerData as { config: unknown; port: MessagePort }

const pipeline = new TestBatchPipeline()
const eventBuffer: PendingEvent[] = []
let processing = false
let flushRequested = false

async function processBuffer(): Promise<void> {
    if (processing || eventBuffer.length === 0) {
        return
    }
    processing = true

    try {
        const batch = eventBuffer.splice(0, eventBuffer.length)

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

        let result: PipelineResultWithContext<TestOutput, WorkerEventContext>[] | null
        while ((result = await pipeline.next()) !== null) {
            for (const item of result) {
                const workerResult = mapPipelineResultToWorkerResult(item.result, item.context.correlationId)
                port.postMessage({ type: 'result', result: workerResult } satisfies WorkerToMainMessage)
            }
        }
    } finally {
        processing = false
    }

    if (eventBuffer.length > 0) {
        setImmediate(() => processBuffer())
    } else if (flushRequested) {
        flushRequested = false
        port.postMessage({ type: 'flush_complete' } satisfies WorkerToMainMessage)
    }
}

function mapPipelineResultToWorkerResult(result: PipelineResult<TestOutput>, correlationId: string): WorkerResult {
    switch (result.type) {
        case PipelineResultType.OK:
            return {
                type: WorkerResultType.OK,
                correlationId,
                value: new TextEncoder().encode(JSON.stringify(result.value)),
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

port.on('message', (msg: MainToWorkerMessage) => {
    switch (msg.type) {
        case 'event': {
            const input = parseJSON(new TextDecoder().decode(msg.data)) as TestInput
            eventBuffer.push({ correlationId: msg.correlationId, input })
            void processBuffer()
            break
        }
        case 'flush': {
            if (eventBuffer.length === 0 && !processing) {
                port.postMessage({ type: 'flush_complete' } satisfies WorkerToMainMessage)
            } else {
                flushRequested = true
                void processBuffer()
            }
            break
        }
        case 'shutdown': {
            process.exit(0)
        }
    }
})

port.ref()
port.postMessage({ type: 'ready' } satisfies WorkerToMainMessage)
