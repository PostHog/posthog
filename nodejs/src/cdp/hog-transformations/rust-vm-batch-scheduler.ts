import { createHash } from 'crypto'
import { Histogram } from 'prom-client'

import { RustExecResult } from './rust-vm'

export const hogvmRustBatchFlushSize = new Histogram({
    name: 'hogvm_rust_batch_flush_size',
    help: 'Number of invocations of one hog program executed in a single executeBatch call',
    buckets: [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000],
})

export type RunBatchFn = (program: unknown[], events: unknown[]) => Promise<RustExecResult[]>

interface QueueEntry {
    globals: unknown
    resolve: (result: RustExecResult) => void
    reject: (error: unknown) => void
}

interface ProgramQueue {
    // The first array instance seen for this program; any instance with the same content will do.
    bytecode: unknown[]
    entries: QueueEntry[]
}

// Above this many queued invocations a program's queue is dispatched immediately instead of
// waiting for the tick to end, bounding how much converted-event memory a single batch holds
// and how long the first waiter sits in the queue. The Rust side derives its rayon chunk size
// from the batch it receives, so this cap doesn't limit fan-out.
export const DEFAULT_MAX_BATCH_SIZE = 500

/**
 * Coalesces individual transformation executions into per-program `executeBatch` calls.
 *
 * Callers `execute(bytecode, globals)` and await their own result; invocations that arrive within
 * the same event-loop tick for the same program are flushed together on the next `setImmediate`
 * as one FFI crossing, executed off the JS thread. Batch sizes therefore track how many events
 * are concurrently at the transform step.
 *
 * "Same program" means same bytecode content, not the same array instance. Every team has its own
 * HogFunction row, so one template (GeoIP on thousands of teams) arrives as thousands of distinct
 * arrays with identical content; keying by instance would keep each team in its own batch.
 *
 * A batch-level failure rejects every waiter in that batch — the caller decides what a rejection
 * means (the executor treats it like a boundary throw and falls back to the Node VM).
 */
export class RustVmBatchScheduler {
    private queues = new Map<string, ProgramQueue>()
    // Content hash per array instance. The hog function manager hands out one cached array per
    // function, so this is computed once per function, not once per invocation.
    private programKeys = new WeakMap<unknown[], string>()
    private flushScheduled = false

    constructor(
        private runBatch: RunBatchFn,
        private maxBatchSize: number = DEFAULT_MAX_BATCH_SIZE
    ) {}

    public execute(bytecode: unknown[], globals: unknown): Promise<RustExecResult> {
        return new Promise((resolve, reject) => {
            const key = this.programKey(bytecode)
            let queue = this.queues.get(key)
            if (!queue) {
                queue = { bytecode, entries: [] }
                this.queues.set(key, queue)
            }
            queue.entries.push({ globals, resolve, reject })

            if (queue.entries.length >= this.maxBatchSize) {
                this.queues.delete(key)
                this.dispatch(queue)
                return
            }

            if (!this.flushScheduled) {
                this.flushScheduled = true
                setImmediate(() => this.flush())
            }
        })
    }

    private programKey(bytecode: unknown[]): string {
        let key = this.programKeys.get(bytecode)
        if (key === undefined) {
            key = createHash('sha256').update(JSON.stringify(bytecode)).digest('base64')
            this.programKeys.set(bytecode, key)
        }
        return key
    }

    private flush(): void {
        this.flushScheduled = false
        const queues = this.queues
        this.queues = new Map()
        for (const queue of queues.values()) {
            this.dispatch(queue)
        }
    }

    private dispatch({ bytecode, entries }: ProgramQueue): void {
        hogvmRustBatchFlushSize.observe(entries.length)
        this.runBatch(
            bytecode,
            entries.map((entry) => entry.globals)
        )
            .then((results) => {
                if (results.length !== entries.length) {
                    throw new Error(`executeBatch returned ${results.length} results for ${entries.length} events`)
                }
                entries.forEach((entry, index) => entry.resolve(results[index]))
            })
            .catch((error) => {
                entries.forEach((entry) => entry.reject(error))
            })
    }
}
