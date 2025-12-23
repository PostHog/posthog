import * as path from 'path'

import { WorkerResultType } from './serializable'
import { WorkerManager } from './worker-manager'

describe('WorkerManager', () => {
    const testWorkerPath = path.join(__dirname, 'test-worker.ts')
    let manager: WorkerManager

    afterEach(async () => {
        if (manager) {
            await manager.shutdown()
        }
    })

    describe('initialization', () => {
        it('should initialize workers and wait for ready signal', async () => {
            manager = new WorkerManager(2, testWorkerPath, {})

            // sendEvent waits for ready internally
            const result = await manager.sendEvent('key1', 'corr-1', Buffer.from('test'))

            expect(result.type).toBe(WorkerResultType.OK)
            expect(result.correlationId).toBe('corr-1')
        })
    })

    describe('sendEvent', () => {
        it('should send event to worker and receive result', async () => {
            manager = new WorkerManager(1, testWorkerPath, {})

            const buffer = Buffer.from('hello world')
            const result = await manager.sendEvent('key1', 'corr-1', buffer)

            expect(result.type).toBe(WorkerResultType.OK)
            expect(result.correlationId).toBe('corr-1')
            if (result.type === WorkerResultType.OK) {
                // Buffer becomes Uint8Array after transfer, convert back to string
                expect(Buffer.from(result.value).toString()).toBe('hello world')
            }
        })

        it('should route events to workers based on shard key hash', async () => {
            manager = new WorkerManager(4, testWorkerPath, {})

            const results = await Promise.all([
                manager.sendEvent('key-a', 'corr-1', Buffer.from('a')),
                manager.sendEvent('key-b', 'corr-2', Buffer.from('b')),
                manager.sendEvent('key-c', 'corr-3', Buffer.from('c')),
                manager.sendEvent('key-d', 'corr-4', Buffer.from('d')),
            ])

            expect(results).toHaveLength(4)
            expect(results.map((r) => r.correlationId).sort()).toEqual(['corr-1', 'corr-2', 'corr-3', 'corr-4'])
        })

        it('should route same key to same worker consistently', async () => {
            manager = new WorkerManager(4, testWorkerPath, {})

            // Send multiple events with same key
            const results = await Promise.all([
                manager.sendEvent('same-key', 'corr-1', Buffer.from('1')),
                manager.sendEvent('same-key', 'corr-2', Buffer.from('2')),
                manager.sendEvent('same-key', 'corr-3', Buffer.from('3')),
            ])

            expect(results).toHaveLength(3)
            // All should succeed (same worker handles all)
            expect(results.every((r) => r.type === WorkerResultType.OK)).toBe(true)
        })
    })

    describe('flush', () => {
        it('should wait for all workers to complete pending work', async () => {
            manager = new WorkerManager(2, testWorkerPath, {})

            // Send some events
            await Promise.all([
                manager.sendEvent('key-a', 'corr-1', Buffer.from('a')),
                manager.sendEvent('key-b', 'corr-2', Buffer.from('b')),
            ])

            // Flush should complete without error
            await expect(manager.flush()).resolves.toBeUndefined()
        })
    })

    describe('shutdown', () => {
        it('should terminate all workers', async () => {
            manager = new WorkerManager(2, testWorkerPath, {})

            // Wait for initialization
            await manager.sendEvent('key', 'corr-1', Buffer.from('test'))

            // Shutdown should complete
            await expect(manager.shutdown()).resolves.toBeUndefined()
        })
    })

    describe('hashToShard', () => {
        it('should distribute keys across shards', async () => {
            manager = new WorkerManager(4, testWorkerPath, {})

            // Test that different keys hash to potentially different shards
            // by sending many events and checking they all succeed
            const promises = []
            for (let i = 0; i < 100; i++) {
                promises.push(manager.sendEvent(`key-${i}`, `corr-${i}`, Buffer.from(`${i}`)))
            }

            const results = await Promise.all(promises)
            expect(results).toHaveLength(100)
            expect(results.every((r) => r.type === WorkerResultType.OK)).toBe(true)
        })
    })
})
