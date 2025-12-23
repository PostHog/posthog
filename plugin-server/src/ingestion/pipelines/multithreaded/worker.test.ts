import * as path from 'path'

import { parseJSON } from '../../../utils/json-parse'
import { WorkerResultType } from './serializable'
import { WorkerManager } from './worker-manager'

/**
 * Tests for the generic worker.ts that uses a configurable pipeline.
 * Uses a test fixture that creates a simple identity pipeline.
 */
describe('Worker with configurable pipeline', () => {
    const testPipelineWorkerPath = path.join(__dirname, 'test-pipeline-worker.ts')
    let manager: WorkerManager

    afterEach(async () => {
        if (manager) {
            await manager.shutdown()
        }
    })

    describe('basic processing', () => {
        it('should process events through configured pipeline', async () => {
            manager = new WorkerManager(1, testPipelineWorkerPath, {})

            const data = new TextEncoder().encode(JSON.stringify({ value: 'test-input' }))
            const result = await manager.sendEvent('key1', 'corr-1', data)

            expect(result.type).toBe(WorkerResultType.OK)
            expect(result.correlationId).toBe('corr-1')

            if (result.type === WorkerResultType.OK) {
                const decoded = parseJSON(new TextDecoder().decode(result.value))
                expect(decoded.processed).toBe(true)
                expect(decoded.original.value).toBe('test-input')
            }
        })

        it('should handle multiple events', async () => {
            manager = new WorkerManager(2, testPipelineWorkerPath, {})

            const results = await Promise.all([
                manager.sendEvent('key-a', 'corr-1', new TextEncoder().encode(JSON.stringify({ id: 1 }))),
                manager.sendEvent('key-b', 'corr-2', new TextEncoder().encode(JSON.stringify({ id: 2 }))),
                manager.sendEvent('key-c', 'corr-3', new TextEncoder().encode(JSON.stringify({ id: 3 }))),
            ])

            expect(results).toHaveLength(3)
            expect(results.every((r) => r.type === WorkerResultType.OK)).toBe(true)

            const correlationIds = results.map((r) => r.correlationId).sort()
            expect(correlationIds).toEqual(['corr-1', 'corr-2', 'corr-3'])
        })
    })

    describe('flush', () => {
        it('should wait for pending work to complete', async () => {
            manager = new WorkerManager(2, testPipelineWorkerPath, {})

            await Promise.all([
                manager.sendEvent('key-a', 'corr-1', new TextEncoder().encode(JSON.stringify({ id: 1 }))),
                manager.sendEvent('key-b', 'corr-2', new TextEncoder().encode(JSON.stringify({ id: 2 }))),
            ])

            await expect(manager.flush()).resolves.toBeUndefined()
        })
    })

    describe('sharding', () => {
        it('should route same key to same worker', async () => {
            manager = new WorkerManager(4, testPipelineWorkerPath, {})

            const results = await Promise.all([
                manager.sendEvent('same-key', 'corr-1', new TextEncoder().encode(JSON.stringify({ id: 1 }))),
                manager.sendEvent('same-key', 'corr-2', new TextEncoder().encode(JSON.stringify({ id: 2 }))),
                manager.sendEvent('same-key', 'corr-3', new TextEncoder().encode(JSON.stringify({ id: 3 }))),
            ])

            expect(results).toHaveLength(3)
            expect(results.every((r) => r.type === WorkerResultType.OK)).toBe(true)
        })
    })
})
