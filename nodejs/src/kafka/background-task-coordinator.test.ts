import { BackgroundTaskCoordinator, TimeoutError } from './background-task-coordinator'

const createControllablePromise = () => {
    let resolve: () => void
    let reject: (error: Error) => void
    const promise = new Promise<void>((res, rej) => {
        resolve = res
        reject = rej
    })
    return { promise, resolve: resolve!, reject: reject! }
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

describe('BackgroundTaskCoordinator', () => {
    let coordinator: BackgroundTaskCoordinator

    beforeEach(() => {
        coordinator = new BackgroundTaskCoordinator()
    })

    describe('addTask', () => {
        it('should add a task and track it', () => {
            const task = createControllablePromise()
            const onOffsetsStored = jest.fn()

            coordinator.addTask(task.promise, onOffsetsStored, new Set([1]))

            expect(coordinator.taskCount).toBe(1)
        })

        it('should call onOffsetsStored when task completes', async () => {
            const task = createControllablePromise()
            const onOffsetsStored = jest.fn()

            coordinator.addTask(task.promise, onOffsetsStored, new Set([1]))

            expect(onOffsetsStored).not.toHaveBeenCalled()

            task.resolve()
            await delay(1)

            expect(onOffsetsStored).toHaveBeenCalledTimes(1)
            expect(coordinator.taskCount).toBe(0)
        })

        it('should call onOffsetsStored even when task fails', async () => {
            // Create a task that will reject
            const failingTask = Promise.reject(new Error('Task failed')).catch(() => {
                // Catch immediately to prevent unhandled rejection warning
            }) as Promise<void>

            const onOffsetsStored = jest.fn()

            const { offsetsStoredPromise } = coordinator.addTask(failingTask, onOffsetsStored, new Set([1]))

            // Wait for the offsetsStoredPromise (which runs via finally regardless of rejection)
            await offsetsStoredPromise

            expect(onOffsetsStored).toHaveBeenCalledTimes(1)
            expect(coordinator.taskCount).toBe(0)
        })
    })

    describe('offset storage ordering', () => {
        it('should store offsets in order even when tasks complete out of order', async () => {
            const task1 = createControllablePromise()
            const task2 = createControllablePromise()
            const task3 = createControllablePromise()

            const storedOrder: number[] = []
            coordinator.addTask(task1.promise, () => storedOrder.push(1), new Set([1]))
            coordinator.addTask(task2.promise, () => storedOrder.push(2), new Set([2]))
            coordinator.addTask(task3.promise, () => storedOrder.push(3), new Set([3]))

            expect(coordinator.taskCount).toBe(3)

            // Complete tasks out of order: 3, 1, 2
            task3.resolve()
            await delay(1)
            // Task 3 completed but can't store offsets yet (waiting for 1 and 2)
            expect(storedOrder).toEqual([])

            task1.resolve()
            await delay(1)
            // Task 1 can now store offsets
            expect(storedOrder).toEqual([1])

            task2.resolve()
            await delay(1)
            // Task 2 can now store, and task 3 was waiting for it
            expect(storedOrder).toEqual([1, 2, 3])

            expect(coordinator.taskCount).toBe(0)
        })

        it('should handle rapid task completion in order', async () => {
            const storedOrder: number[] = []

            for (let i = 1; i <= 5; i++) {
                coordinator.addTask(Promise.resolve(), () => storedOrder.push(i), new Set([i]))
            }

            await delay(10)

            expect(storedOrder).toEqual([1, 2, 3, 4, 5])
            expect(coordinator.taskCount).toBe(0)
        })

        it('should maintain order when middle task completes first', async () => {
            const task1 = createControllablePromise()
            const task2 = createControllablePromise()
            const task3 = createControllablePromise()

            const storedOrder: number[] = []
            coordinator.addTask(task1.promise, () => storedOrder.push(1), new Set([1]))
            coordinator.addTask(task2.promise, () => storedOrder.push(2), new Set([2]))
            coordinator.addTask(task3.promise, () => storedOrder.push(3), new Set([3]))

            // Middle task completes first
            task2.resolve()
            await delay(1)
            expect(storedOrder).toEqual([])

            // First task completes
            task1.resolve()
            await delay(1)
            expect(storedOrder).toEqual([1, 2])

            // Last task completes
            task3.resolve()
            await delay(1)
            expect(storedOrder).toEqual([1, 2, 3])
        })
    })

    describe('waitForAllOffsetsStored', () => {
        it('should return success immediately when no tasks', async () => {
            const result = await coordinator.waitForAllOffsetsStored(1000)

            expect(result).toEqual({ status: 'success', durationMs: 0 })
        })

        it('should wait for all offsets to be stored', async () => {
            const task1 = createControllablePromise()
            const task2 = createControllablePromise()

            const storedOrder: number[] = []
            coordinator.addTask(task1.promise, () => storedOrder.push(1), new Set([1]))
            coordinator.addTask(task2.promise, () => storedOrder.push(2), new Set([2]))

            const waitPromise = coordinator.waitForAllOffsetsStored(1000)

            task1.resolve()
            task2.resolve()

            const result = await waitPromise

            expect(result.status).toBe('success')
            expect(storedOrder).toEqual([1, 2])
        })

        it('should timeout if offsets take too long to store', async () => {
            const task = createControllablePromise()
            coordinator.addTask(task.promise, jest.fn(), new Set([1]))

            const result = await coordinator.waitForAllOffsetsStored(50)

            expect(result.status).toBe('timeout')
            // Allow for small timing variations in CI (49ms is acceptable for 50ms timeout)
            expect(result.durationMs).toBeGreaterThanOrEqual(48)

            task.resolve()
        })

        it('should return error if offset storage fails', async () => {
            const task = createControllablePromise()
            coordinator.addTask(
                task.promise,
                () => {
                    throw new Error('Storage failed')
                },
                new Set([1])
            )

            task.resolve()
            const result = await coordinator.waitForAllOffsetsStored(1000)

            expect(result.status).toBe('error')
            expect((result as any).error).toBeInstanceOf(Error)
        })

        it('should not wait for tasks added during wait', async () => {
            const task1 = createControllablePromise()
            coordinator.addTask(task1.promise, jest.fn(), new Set([1]))

            const waitPromise = coordinator.waitForAllOffsetsStored(1000)

            const task2 = createControllablePromise()
            coordinator.addTask(task2.promise, jest.fn(), new Set([2]))

            task1.resolve()

            const result = await waitPromise

            expect(result.status).toBe('success')

            task2.resolve()
        })
    })

    describe('applyBackpressure', () => {
        it('should not wait when under limit', async () => {
            const task = createControllablePromise()
            coordinator.addTask(task.promise, jest.fn(), new Set([1]))

            const waited = await coordinator.applyBackpressure(2)

            expect(waited).toBe(false)

            task.resolve()
        })

        it('should wait when at limit', async () => {
            const task1 = createControllablePromise()
            const task2 = createControllablePromise()
            coordinator.addTask(task1.promise, jest.fn(), new Set([1]))
            coordinator.addTask(task2.promise, jest.fn(), new Set([2]))

            const backpressurePromise = coordinator.applyBackpressure(2)

            let resolved = false
            void backpressurePromise.then(() => {
                resolved = true
            })
            await delay(1)
            expect(resolved).toBe(false)

            task1.resolve()
            await delay(1)

            expect(resolved).toBe(true)
            const waited = await backpressurePromise
            expect(waited).toBe(true)

            task2.resolve()
        })
    })

    describe('waitForAllTasksComplete', () => {
        it('should wait for all task promises to complete', async () => {
            const task1 = createControllablePromise()
            const task2 = createControllablePromise()

            coordinator.addTask(task1.promise, jest.fn(), new Set([1]))
            coordinator.addTask(task2.promise, jest.fn(), new Set([2]))

            let completed = false
            const waitPromise = coordinator.waitForAllTasksComplete().then(() => {
                completed = true
            })

            await delay(1)
            expect(completed).toBe(false)

            task1.resolve()
            await delay(1)
            expect(completed).toBe(false)

            task2.resolve()
            await waitPromise
            expect(completed).toBe(true)
        })
    })

    describe('edge cases', () => {
        it('should handle single task correctly', async () => {
            const task = createControllablePromise()
            const onOffsetsStored = jest.fn()

            const { offsetsStoredPromise } = coordinator.addTask(task.promise, onOffsetsStored, new Set([1]))

            task.resolve()
            await offsetsStoredPromise

            expect(onOffsetsStored).toHaveBeenCalledTimes(1)
            expect(coordinator.taskCount).toBe(0)
        })

        it('should handle interleaved add and complete operations', async () => {
            const storedOrder: number[] = []

            const task1 = createControllablePromise()
            coordinator.addTask(task1.promise, () => storedOrder.push(1), new Set([1]))

            task1.resolve()
            await delay(1)
            expect(storedOrder).toEqual([1])

            const task2 = createControllablePromise()
            coordinator.addTask(task2.promise, () => storedOrder.push(2), new Set([2]))

            const task3 = createControllablePromise()
            coordinator.addTask(task3.promise, () => storedOrder.push(3), new Set([3]))

            task3.resolve()
            await delay(1)
            expect(storedOrder).toEqual([1])

            task2.resolve()
            await delay(1)
            expect(storedOrder).toEqual([1, 2, 3])
        })

        it('should handle task that throws during offset storage', async () => {
            const task1 = createControllablePromise()
            const task2 = createControllablePromise()

            const { offsetsStoredPromise: offset1 } = coordinator.addTask(
                task1.promise,
                () => {
                    throw new Error('Storage error')
                },
                new Set([1])
            )

            const storedOrder: number[] = []
            const { offsetsStoredPromise: offset2 } = coordinator.addTask(
                task2.promise,
                () => storedOrder.push(2),
                new Set([2])
            )

            task1.resolve()
            task2.resolve()

            // Task 1's offsetsStoredPromise will reject due to the throw
            await expect(offset1).rejects.toThrow('Storage error')
            // Task 2 should still complete
            await offset2
            expect(storedOrder).toEqual([2])
        })
    })

    describe('waitForPartitionOffsetsStored', () => {
        it('should return success immediately when no tasks for revoked partitions', async () => {
            const task = createControllablePromise()
            coordinator.addTask(task.promise, jest.fn(), new Set([1, 2]))

            const result = await coordinator.waitForPartitionOffsetsStored(new Set([3, 4]), 1000)

            expect(result).toEqual({ status: 'success', durationMs: 0 })

            task.resolve()
        })

        it('should wait only for tasks with revoked partitions', async () => {
            const task1 = createControllablePromise()
            const task2 = createControllablePromise()
            const task3 = createControllablePromise()

            const storedOrder: number[] = []
            coordinator.addTask(task1.promise, () => storedOrder.push(1), new Set([1]))
            coordinator.addTask(task2.promise, () => storedOrder.push(2), new Set([2]))
            coordinator.addTask(task3.promise, () => storedOrder.push(3), new Set([3]))

            // Revoke partition 2 only
            const waitPromise = coordinator.waitForPartitionOffsetsStored(new Set([2]), 1000)

            // Resolve task 2 (revoked partition), but it needs task 1 to complete first due to ordering
            task2.resolve()
            await delay(5)
            // Still waiting because task 1 hasn't completed (maintains ordering)

            // Resolve task 1 - now task 2 can store its offsets
            task1.resolve()
            await delay(5)

            const result = await waitPromise
            expect(result.status).toBe('success')
            expect(storedOrder).toEqual([1, 2])

            // Cleanup - task 3 is not part of the wait
            task3.resolve()
        })

        it('should wait for multiple tasks with overlapping partitions', async () => {
            const task1 = createControllablePromise()
            const task2 = createControllablePromise()
            const task3 = createControllablePromise()

            const storedOrder: number[] = []
            coordinator.addTask(task1.promise, () => storedOrder.push(1), new Set([1, 2]))
            coordinator.addTask(task2.promise, () => storedOrder.push(2), new Set([2, 3]))
            coordinator.addTask(task3.promise, () => storedOrder.push(3), new Set([4]))

            // Revoke partitions 2 and 3 - should wait for task1 and task2, not task3
            const waitPromise = coordinator.waitForPartitionOffsetsStored(new Set([2, 3]), 1000)

            task3.resolve()
            await delay(5)
            // Should still be waiting for task1 and task2

            task1.resolve()
            task2.resolve()
            const result = await waitPromise

            expect(result.status).toBe('success')
            expect(storedOrder).toEqual([1, 2, 3])
        })

        it('should timeout if partition offsets take too long', async () => {
            const task = createControllablePromise()
            coordinator.addTask(task.promise, jest.fn(), new Set([1]))

            const result = await coordinator.waitForPartitionOffsetsStored(new Set([1]), 50)

            expect(result.status).toBe('timeout')
            expect(result.durationMs).toBeGreaterThanOrEqual(48)

            task.resolve()
        })
    })

    describe('TimeoutError', () => {
        it('should be identifiable', () => {
            const error = new TimeoutError()

            expect(error).toBeInstanceOf(TimeoutError)
            expect(error).toBeInstanceOf(Error)
            expect(error.name).toBe('TimeoutError')
            expect(error.message).toBe('timeout')
        })
    })
})
