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
        return [...this.tasks]
    }

    /**
     * Adds a background task and returns the offsetsStoredPromise.
     *
     * The offsetsStoredPromise will resolve only after:
     * 1. The task completes (success or failure via finally)
     * 2. All earlier tasks' offsets have been stored
     * 3. The onOffsetsStored callback has been called
     *
     * @param taskPromise - The background work promise
     * @param onOffsetsStored - Callback to store offsets (called in order)
     * @returns The task descriptor with offsetsStoredPromise
     */
    addTask(taskPromise: Promise<void>, onOffsetsStored: () => void): BackgroundTask {
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

            // Capture promises to wait for BEFORE removing ourselves
            // We wait for offsetsStoredPromise (not just promise) to ensure offsets are stored in order
            const promisesToWait = this.tasks.slice(0, index).map((t) => t.offsetsStoredPromise)

            // Remove ourselves from the queue
            this.tasks.splice(index, 1)

            // Wait for all earlier tasks to store their offsets
            await Promise.all(promisesToWait)

            // Now it's safe to store our offsets
            onOffsetsStored()
        })

        const task: BackgroundTask = {
            promise: taskPromise,
            createdAt,
            offsetsStoredPromise,
        }

        this.tasks.push(task)
        return task
    }

    /**
     * Waits for all current tasks' offsets to be stored, with timeout.
     *
     * Use this during rebalance to ensure offsets are committed before partition release.
     * For shutdown without timeout, use {@link waitForAllTasksComplete} instead.
     *
     * @param timeoutMs - Maximum time to wait before giving up
     * @returns Result indicating success, timeout, or error
     */
    async waitForAllOffsetsStored(timeoutMs: number): Promise<WaitResult> {
        const startTime = Date.now()

        if (this.tasks.length === 0) {
            return { status: 'success', durationMs: 0 }
        }

        // Capture current tasks - new tasks added during wait are not our concern
        const tasksToWait = [...this.tasks]

        // Wait for all offsets to be stored
        const offsetsStoredPromise = Promise.all(tasksToWait.map((t) => t.offsetsStoredPromise))

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
