import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { sleep } from '~/common/utils/utils'
import { FeedRejectionKind } from '~/ingestion/framework/batching-pipeline'
import { OkResultWithContext } from '~/ingestion/framework/chunk-pipeline.interface'
import {
    JoinedIngestionPipelineContext,
    JoinedIngestionPipelineInput,
    createJoinedIngestionPipeline,
} from '~/ingestion/pipelines/analytics/joined-ingestion-pipeline'

/** Batch context fed with each HTTP batch so its completion routes back to the request that fed it. */
export type HttpBatchContext = { httpBatchSeq: number }

export type HttpIngestPipeline = ReturnType<
    typeof createJoinedIngestionPipeline<JoinedIngestionPipelineInput, JoinedIngestionPipelineContext, HttpBatchContext>
>

export type HttpIngestBatch = OkResultWithContext<JoinedIngestionPipelineInput, JoinedIngestionPipelineContext>[]

export type HttpFeedResult =
    | {
          ok: true
          /** Resolves once this batch and its side effects are durably done: the response barrier. */
          settled: Promise<void>
      }
    | { ok: false; kind: FeedRejectionKind; reason: string }

interface Waiter {
    resolve: () => void
    reject: (error: Error) => void
}

/**
 * Routes each completed HTTP batch back to the request that fed it. The
 * pipeline's next() hands out completions in completion order with no regard
 * for who is waiting, so a request that drained next() itself would consume
 * (and discard) other requests' completions and only get to respond once the
 * whole pipeline went idle. Under sustained load that never happens. One
 * pump loop per server drains next() instead, and completions carry the
 * feeding request's sequence number, so a slow batch only delays its own
 * response.
 */
export class HttpIngestPump {
    private nextSeq = 0
    private waiters = new Map<number, Waiter>()
    private wakePump: (() => void) | null = null
    private pumpTask: Promise<void> | null = null
    private stopped = false
    private fatalError?: Error

    constructor(
        private pipeline: HttpIngestPipeline,
        private promiseScheduler: PromiseScheduler,
        private pumpIdleMs = 20
    ) {}

    start(): void {
        this.pumpTask = this.runPump()
    }

    async stop(): Promise<void> {
        this.stopped = true
        this.wake()
        if (!this.pumpTask) {
            return
        }
        let deadline: NodeJS.Timeout | undefined
        try {
            await Promise.race([
                this.pumpTask,
                new Promise<void>((resolve) => {
                    deadline = setTimeout(resolve, 5_000)
                }),
            ])
        } finally {
            clearTimeout(deadline)
        }
    }

    async feed(batch: HttpIngestBatch): Promise<HttpFeedResult> {
        if (this.fatalError) {
            throw this.fatalError
        }
        if (!this.pumpTask) {
            this.start()
        }
        const seq = this.nextSeq++
        const settled = new Promise<void>((resolve, reject) => {
            this.waiters.set(seq, { resolve, reject })
        })
        let result: Awaited<ReturnType<HttpIngestPipeline['feed']>>
        try {
            result = await this.pipeline.feed(batch, { httpBatchSeq: seq })
        } catch (error) {
            this.waiters.delete(seq)
            throw error
        }
        if (!result.ok) {
            this.waiters.delete(seq)
            return result
        }
        this.wake()
        return { ok: true, settled }
    }

    private wake(): void {
        if (this.wakePump) {
            const wake = this.wakePump
            this.wakePump = null
            wake()
        }
    }

    private async runPump(): Promise<void> {
        while (!this.stopped || this.waiters.size > 0) {
            if (this.waiters.size === 0) {
                await new Promise<void>((resolve) => {
                    this.wakePump = resolve
                })
                continue
            }
            let completed: Awaited<ReturnType<HttpIngestPipeline['next']>>
            try {
                completed = await this.pipeline.next()
            } catch (error) {
                this.poison(error instanceof Error ? error : new Error(String(error)))
                return
            }
            if (completed === null) {
                await sleep(this.pumpIdleMs)
                continue
            }
            const waiter = this.waiters.get(completed.batchContext.httpBatchSeq)
            this.waiters.delete(completed.batchContext.httpBatchSeq)
            this.settle(waiter, completed.sideEffects ?? [])
        }
    }

    private settle(waiter: Waiter | undefined, sideEffects: Promise<unknown>[]): void {
        void (async () => {
            try {
                await Promise.all(sideEffects)
                await this.promiseScheduler.waitForAll()
                waiter?.resolve()
            } catch (error) {
                waiter?.reject(error instanceof Error ? error : new Error(String(error)))
            }
        })()
    }

    private poison(error: Error): void {
        this.fatalError = error
        const waiters = [...this.waiters.values()]
        this.waiters.clear()
        for (const waiter of waiters) {
            waiter.reject(error)
        }
    }
}
