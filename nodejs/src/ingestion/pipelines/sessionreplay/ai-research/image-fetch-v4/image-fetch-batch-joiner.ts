import { Message } from 'node-rdkafka'

import { ImageFetchProcessingMetrics, ProcessingStageTimer } from './processing-metrics'

export const IMAGE_FETCH_BATCH_JOIN_TIMEOUT_MS = 500
export const MAX_IMAGE_FETCH_BATCHES_PER_PASS = 16

type BatchProcessor = (messages: Message[]) => Promise<void>

type DispatchedBatch = { backgroundTask: Promise<void> }

type BatchWaiter = {
    resolve: (batch: DispatchedBatch) => void
    reject: (error: unknown) => void
    timer: ProcessingStageTimer
}

type PendingBatchGroup = {
    batches: Message[][]
    waiters: BatchWaiter[]
    timeout?: NodeJS.Timeout
}

export function assertImageFetchBatchTarget(targetBatchCount: number): void {
    if (
        !Number.isSafeInteger(targetBatchCount) ||
        targetBatchCount < 1 ||
        targetBatchCount > MAX_IMAGE_FETCH_BATCHES_PER_PASS
    ) {
        throw new Error(`image fetch batch target must be an integer between 1 and ${MAX_IMAGE_FETCH_BATCHES_PER_PASS}`)
    }
}

export class ImageFetchBatchJoiner {
    private pendingGroup?: PendingBatchGroup
    private readonly activeProcessing = new Set<Promise<void>>()
    private failed = false
    private failure: unknown

    constructor(
        private readonly targetBatchCount: number,
        private readonly processBatch: BatchProcessor
    ) {
        assertImageFetchBatchTarget(targetBatchCount)
    }

    public handleBatch(messages: Message[]): Promise<DispatchedBatch | void> {
        if (messages.length === 0) {
            return Promise.resolve()
        }
        if (this.failed) {
            return Promise.reject(this.failure)
        }

        return new Promise<DispatchedBatch>((resolve, reject) => {
            const group = this.pendingGroup ?? this.createPendingGroup()
            group.batches.push(messages)
            group.waiters.push({ resolve, reject, timer: ImageFetchProcessingMetrics.start('consumer_join') })
            if (group.batches.length >= this.targetBatchCount) {
                this.dispatch(group)
            }
        })
    }

    public async waitForProcessing(): Promise<void> {
        await Promise.allSettled(this.activeProcessing)
    }

    private createPendingGroup(): PendingBatchGroup {
        const group: PendingBatchGroup = { batches: [], waiters: [] }
        group.timeout = setTimeout(() => this.dispatch(group), IMAGE_FETCH_BATCH_JOIN_TIMEOUT_MS)
        this.pendingGroup = group
        return group
    }

    private dispatch(group: PendingBatchGroup): void {
        if (this.pendingGroup !== group) {
            return
        }
        this.pendingGroup = undefined
        if (group.timeout) {
            clearTimeout(group.timeout)
        }

        ImageFetchProcessingMetrics.joinedBatches.observe(group.batches.length)
        for (const { timer } of group.waiters) {
            timer.move('consumer_process')
        }
        const processing = (async () => {
            if (this.failed) {
                throw this.failure
            }
            try {
                await this.processBatch(group.batches.flat())
            } catch (error) {
                this.fail(error)
                throw error
            }
        })().finally(() => {
            group.waiters.forEach(({ timer }) => timer.finish())
            this.activeProcessing.delete(processing)
        })
        this.activeProcessing.add(processing)
        for (const { resolve } of group.waiters) {
            resolve({ backgroundTask: processing })
        }
    }

    private fail(error: unknown): void {
        if (!this.failed) {
            this.failed = true
            this.failure = error
        }

        const pendingGroup = this.pendingGroup
        if (!pendingGroup) {
            return
        }
        this.pendingGroup = undefined
        if (pendingGroup.timeout) {
            clearTimeout(pendingGroup.timeout)
        }
        for (const { reject, timer } of pendingGroup.waiters) {
            timer.finish()
            reject(this.failure)
        }
    }
}
