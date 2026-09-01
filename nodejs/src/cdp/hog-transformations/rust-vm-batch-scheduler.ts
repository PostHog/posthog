import { Histogram } from 'prom-client'

import { RustExecResult } from './rust-vm'

export const hogvmRustBatchFlushSize = new Histogram({
    name: 'hogvm_rust_batch_flush_size',
    help: 'Number of invocations of one hog program executed in a single batch call',
    buckets: [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000],
})

export type RunBatchFn<P> = (program: P, events: unknown[]) => Promise<RustExecResult[]>

interface QueueEntry {
    globals: unknown
    resolve: (result: RustExecResult) => void
    reject: (error: unknown) => void
}

// Above this many queued invocations a program's queue is dispatched immediately instead of
// waiting for the tick to end, bounding how much converted-event memory a single batch holds
// and how long the first waiter sits in the queue. The Rust side derives its rayon chunk size
// from the batch it receives, so this cap doesn't limit fan-out.
export const DEFAULT_MAX_BATCH_SIZE = 500

/**
 * Coalesces individual transformation executions into per-program batch calls.
 *
 * Callers `execute(program, globals)` and await their own result; invocations that arrive within
 * the same event-loop tick for the same program (keyed by the program's object reference — stable
 * while the hog function manager caches the function, and a new version's new object simply
 * starts its own batch) are flushed together on the next `setImmediate` as one FFI crossing,
 * executed off the JS thread. Batch sizes therefore track how many events are concurrently at the
 * transform step. The program is otherwise opaque to the scheduler: `runBatch` decides how to
 * execute it.
 *
 * A batch-level failure rejects every waiter in that batch — the caller decides what a rejection
 * means (the executor treats it like a boundary throw and falls back to the Node VM).
 */
export class RustVmBatchScheduler<P> {
    private queues = new Map<P, QueueEntry[]>()
    private flushScheduled = false

    constructor(
        private runBatch: RunBatchFn<P>,
        private maxBatchSize: number = DEFAULT_MAX_BATCH_SIZE
    ) {}

    public execute(program: P, globals: unknown): Promise<RustExecResult> {
        return new Promise((resolve, reject) => {
            let queue = this.queues.get(program)
            if (!queue) {
                queue = []
                this.queues.set(program, queue)
            }
            queue.push({ globals, resolve, reject })

            if (queue.length >= this.maxBatchSize) {
                this.queues.delete(program)
                this.dispatch(program, queue)
                return
            }

            if (!this.flushScheduled) {
                this.flushScheduled = true
                setImmediate(() => this.flush())
            }
        })
    }

    private flush(): void {
        this.flushScheduled = false
        const queues = this.queues
        this.queues = new Map()
        for (const [program, entries] of queues) {
            this.dispatch(program, entries)
        }
    }

    private dispatch(program: P, entries: QueueEntry[]): void {
        hogvmRustBatchFlushSize.observe(entries.length)
        this.runBatch(
            program,
            entries.map((entry) => entry.globals)
        )
            .then((results) => {
                if (results.length !== entries.length) {
                    throw new Error(`batch returned ${results.length} results for ${entries.length} events`)
                }
                entries.forEach((entry, index) => entry.resolve(results[index]))
            })
            .catch((error) => {
                entries.forEach((entry) => entry.reject(error))
            })
    }
}
