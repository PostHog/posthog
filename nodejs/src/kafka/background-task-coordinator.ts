/**
 * BackgroundTaskCoordinator manages background task execution with ordered offset storage.
 *
 * The key invariant this class maintains: offsets must be stored in the same order
 * that batches were consumed. This prevents out-of-order commits which could cause
 * duplicate message processing after a rebalance.
 *
 * How it works:
 * 1. Each task has a `promise` (the actual work) and an `offsetsStoredPromise`
 * 2. The `offsetsStoredPromise` only resolves AFTER:
 *    - The task's promise completes (success or failure)
 *    - All earlier tasks' offsets have been stored
 * 3. During rebalance, we wait for all `offsetsStoredPromise` to complete before
 *    committing offsets and releasing partitions
 */
import { captureException } from '../utils/posthog'

export interface BackgroundTask {
    promise: Promise<void>
    createdAt: number
    offsetsStoredPromise: Promise<void>
    partitions: Set<number>
}

export interface TaskCompletionCallback {
    (offsets: { topic: string; partition: number; offset: number }[]): void
}

export class TimeoutError extends Error {
    constructor() {
        super('timeout')
        this.name = 'TimeoutError'
    }
}

export type WaitResult =
    | { status: 'success'; durationMs: number }
    | { status: 'timeout'; durationMs: number }
    | { status: 'error'; durationMs: number; error: unknown }

export class BackgroundTaskCoordinator {
    private tasks: BackgroundTask[] = []

    /**
     * Returns the current number of pending tasks
     */
    get taskCount(): number {
        return this.tasks.length
    }

    /**
     * Returns a snapshot of current tasks (for rebalance waiting)
     */
    get pendingTasks(): readonly BackgroundTask[] {
        return Array.from(this.tasks)
    }

    /**
     * Adds a background task and returns the offsetsStoredPromise.
     *
     * The offsetsStoredPromise will resolve only after:
     * 1. The task completes (success or failure via finally)
     * 2. All earlier tasks' offsets have been stored
     * 3. The storeOffsets callback has been called
     *
     * @param taskPromise - The background work promise
     * @param storeOffsets - Callback that stores offsets (called in order after predecessors complete)
     * @param partitions - Set of partition IDs this task is processing
     * @returns The task descriptor with offsetsStoredPromise
     */
    addTask(taskPromise: Promise<void>, storeOffsets: () => void, partitions: Set<number>): BackgroundTask {
        const createdAt = Date.now()

        // Create the offset storage promise that chains through finally
        const offsetsStoredPromise = taskPromise.finally(async () => {
            // Find our position in the queue
            const index = this.tasks.findIndex((t) => t.promise === taskPromise)

            if (index < 0) {
                // Task not found - this indicates a bug
                captureException(new Error('Background task not found in array during cleanup'))
                return
            }

            // Capture the previous task's offsetsStoredPromise BEFORE removing ourselves.
            // We only need to wait for the immediate predecessor since each task transitively
            // waits for all its predecessors, making this O(n) instead of O(n^2).
            const previousTask = index > 0 ? this.tasks[index - 1] : null

            // Remove ourselves from the queue
            this.tasks.splice(index, 1)

            // Wait for the previous task to store its offsets (which transitively waits for all earlier tasks)
            if (previousTask) {
                await previousTask.offsetsStoredPromise
            }

            // Now it's safe to store our offsets
            storeOffsets()
        })

        const task: BackgroundTask = {
            promise: taskPromise,
            createdAt,
            offsetsStoredPromise,
            partitions,
        }

        this.tasks.push(task)
        return task
    }

    /**
     * Waits for all current tasks' offsets to be stored, with optional timeout.
     *
     * Use this during rebalance to ensure offsets are committed before partition release.
     * For shutdown, call without timeout to wait indefinitely.
     *
     * @param timeoutMs - Optional maximum time to wait before giving up. If not provided, waits indefinitely.
     * @returns Result indicating success, timeout, or error
     */
    async waitForAllOffsetsStored(timeoutMs?: number): Promise<WaitResult> {
        const startTime = Date.now()

        if (this.tasks.length === 0) {
            return { status: 'success', durationMs: 0 }
        }

        // We only need to await the last task's offsetsStoredPromise since each task
        // transitively waits for all its predecessors before storing offsets.
        const lastTask = this.tasks[this.tasks.length - 1]
        const offsetsStoredPromise = lastTask.offsetsStoredPromise

        // If no timeout, just wait for completion
        if (timeoutMs === undefined) {
            try {
                await offsetsStoredPromise
                return { status: 'success', durationMs: Date.now() - startTime }
            } catch (error) {
                return { status: 'error', durationMs: Date.now() - startTime, error }
            }
        }

        // Create timeout promise
        let timeoutId: NodeJS.Timeout | undefined
        try {
            const timeoutPromise = new Promise<never>((_, reject) => {
                timeoutId = setTimeout(() => reject(new TimeoutError()), timeoutMs)
            })

            await Promise.race([offsetsStoredPromise, timeoutPromise])
            return { status: 'success', durationMs: Date.now() - startTime }
        } catch (error) {
            const durationMs = Date.now() - startTime

            if (error instanceof TimeoutError) {
                return { status: 'timeout', durationMs }
            }

            return { status: 'error', durationMs, error }
        } finally {
            if (timeoutId) {
                clearTimeout(timeoutId)
            }
        }
    }

    /**
     * Waits for offsets to be stored for tasks processing specific partitions, with timeout.
     *
     * Use this during rebalance to wait only for tasks from revoked partitions.
     * This allows continued processing of non-revoked partitions without blocking.
     *
     * @param partitionIds - Set of partition IDs to wait for
     * @param timeoutMs - Maximum time to wait before giving up
     * @returns Result indicating success, timeout, or error
     */
    async waitForPartitionOffsetsStored(partitionIds: Set<number>, timeoutMs: number): Promise<WaitResult> {
        const startTime = Date.now()

        // Filter tasks that touch any of the revoked partitions
        const relevantTasks = this.tasks.filter((task) => {
            // Task is relevant if it has any partition in common with revoked partitions
            for (const partition of task.partitions) {
                if (partitionIds.has(partition)) {
                    return true
                }
            }
            return false
        })

        if (relevantTasks.length === 0) {
            return { status: 'success', durationMs: 0 }
        }

        // Wait for all relevant tasks' offsets to be stored
        const offsetsStoredPromises = relevantTasks.map((t) => t.offsetsStoredPromise)

        let timeoutId: NodeJS.Timeout | undefined
        try {
            const timeoutPromise = new Promise<never>((_, reject) => {
                timeoutId = setTimeout(() => reject(new TimeoutError()), timeoutMs)
            })

            await Promise.race([Promise.all(offsetsStoredPromises), timeoutPromise])
            return { status: 'success', durationMs: Date.now() - startTime }
        } catch (error) {
            const durationMs = Date.now() - startTime

            if (error instanceof TimeoutError) {
                return { status: 'timeout', durationMs }
            }

            return { status: 'error', durationMs, error }
        } finally {
            if (timeoutId) {
                clearTimeout(timeoutId)
            }
        }
    }

    /**
     * Waits for all task promises to complete (not just offset storage).
     *
     * Use this during shutdown to ensure all work finishes before disconnect.
     * For rebalance with timeout, use {@link waitForAllOffsetsStored} instead.
     */
    async waitForAllTasksComplete(): Promise<void> {
        await Promise.all(this.tasks.map((t) => t.promise))
    }

    /**
     * Applies backpressure by waiting for the oldest task if we have too many.
     *
     * @param maxTasks - Maximum number of concurrent tasks allowed
     * @returns true if we had to wait, false otherwise
     */
    async applyBackpressure(maxTasks: number): Promise<boolean> {
        if (this.tasks.length >= maxTasks) {
            await this.tasks[0].promise
            return true
        }
        return false
    }

    /**
     * Clears all tasks. Use with caution - mainly for testing.
     */
    clear(): void {
        this.tasks = []
    }
}
