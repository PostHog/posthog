import {
    DecompressionWorkerManager,
    getDecompressionWorkerManager,
    terminateDecompressionWorker,
} from './DecompressionWorkerManager'

// jest.setup.ts mocks this module globally (to dodge import.meta.url in the worker chain);
// these tests exercise the real implementation, with only the WASM dependency mocked.
jest.unmock('./DecompressionWorkerManager')
jest.mock('snappy-wasm')

describe('DecompressionWorkerManager', () => {
    let manager: DecompressionWorkerManager

    beforeEach(() => {
        manager = new DecompressionWorkerManager()
    })

    afterEach(() => {
        manager.terminate()
    })

    describe('decompress', () => {
        it('decompresses data successfully', async () => {
            const data = new Uint8Array([1, 2, 3, 4, 5])
            const result = await manager.decompress(data)

            expect(result).toBeInstanceOf(Uint8Array)
            expect(result).toEqual(data)
        })

        it('handles multiple sequential decompressions', async () => {
            const data1 = new Uint8Array([1, 2, 3])
            const data2 = new Uint8Array([4, 5, 6])
            const data3 = new Uint8Array([7, 8, 9])

            const result1 = await manager.decompress(data1)
            const result2 = await manager.decompress(data2)
            const result3 = await manager.decompress(data3)

            expect(result1).toEqual(data1)
            expect(result2).toEqual(data2)
            expect(result3).toEqual(data3)
        })

        it('handles multiple concurrent decompressions', async () => {
            const data1 = new Uint8Array([1, 2, 3])
            const data2 = new Uint8Array([4, 5, 6])
            const data3 = new Uint8Array([7, 8, 9])

            const [result1, result2, result3] = await Promise.all([
                manager.decompress(data1),
                manager.decompress(data2),
                manager.decompress(data3),
            ])

            expect(result1).toEqual(data1)
            expect(result2).toEqual(data2)
            expect(result3).toEqual(data3)
        })
    })

    describe('terminate', () => {
        it('terminates the manager successfully', () => {
            expect(() => manager.terminate()).not.toThrow()
        })
    })

    describe('worker path resilience', () => {
        type MockBehavior = 'ready' | 'decompress-error-response'

        class MockWorker {
            static instances: MockWorker[] = []
            static behavior: MockBehavior = 'ready'

            listeners: Record<string, ((event: any) => void)[]> = {}
            postMessage = jest.fn((message: any) => {
                setTimeout(() => {
                    if (MockWorker.behavior === 'decompress-error-response') {
                        this.emit('message', { data: { id: message.id, decompressedData: null, error: 'boom' } })
                    } else {
                        this.emit('message', { data: { id: message.id, decompressedData: message.compressedData } })
                    }
                }, 0)
            })
            terminate = jest.fn()

            constructor() {
                MockWorker.instances.push(this)
                // Workers post a `ready` message synchronously on module eval; emulate that on the next tick
                setTimeout(() => this.emit('message', { data: { type: 'ready' } }), 0)
            }

            addEventListener(type: string, cb: (event: any) => void): void {
                ;(this.listeners[type] ||= []).push(cb)
            }
            removeEventListener(type: string, cb: (event: any) => void): void {
                this.listeners[type] = (this.listeners[type] || []).filter((fn) => fn !== cb)
            }
            emit(type: string, event: any): void {
                ;(this.listeners[type] || []).slice().forEach((cb) => cb(event))
            }
        }

        const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 5))
        const originalWorker = (global as any).Worker

        beforeEach(() => {
            MockWorker.instances = []
            MockWorker.behavior = 'ready'
            ;(global as any).Worker = MockWorker
        })

        afterEach(() => {
            ;(global as any).Worker = originalWorker
        })

        it('decompresses off-thread when the worker is available', async () => {
            const workerManager = new DecompressionWorkerManager()
            await flush()

            const data = new Uint8Array([1, 2, 3])
            const result = await workerManager.decompress(data)

            expect(result).toEqual(data)
            expect(MockWorker.instances).toHaveLength(1)
            expect(MockWorker.instances[0].postMessage).toHaveBeenCalledTimes(1)

            workerManager.terminate()
        })

        it('recovers from a mid-session worker crash instead of routing chunks to a dead worker', async () => {
            const workerManager = new DecompressionWorkerManager()
            await flush()
            expect(MockWorker.instances).toHaveLength(1)

            // Simulate the worker crashing after it became ready
            MockWorker.instances[0].emit('error', { message: 'crash' })
            expect(MockWorker.instances[0].terminate).toHaveBeenCalled()

            // Next decompression must still resolve quickly (not stall on the dead worker)
            const data = new Uint8Array([4, 5, 6])
            const result = await workerManager.decompress(data)
            await flush()

            expect(result).toEqual(data)
            // A fresh worker is spun up to keep decompression off the main thread
            expect(MockWorker.instances.length).toBeGreaterThan(1)

            workerManager.terminate()
        })

        it('stops using the worker after repeated decompression failures', async () => {
            MockWorker.behavior = 'decompress-error-response'
            const workerManager = new DecompressionWorkerManager()
            await flush()

            const data = new Uint8Array([7, 8, 9])
            // Each call falls back to the main thread; after the failure threshold the
            // worker is abandoned and no further messages are posted to it
            await workerManager.decompress(data)
            await workerManager.decompress(data)
            const result = await workerManager.decompress(data)
            const postMessageCallsAfterThreshold = MockWorker.instances[0].postMessage.mock.calls.length

            await workerManager.decompress(data)

            expect(result).toEqual(data)
            expect(MockWorker.instances[0].postMessage.mock.calls.length).toEqual(postMessageCallsAfterThreshold)

            workerManager.terminate()
        })
    })

    describe('singleton functions', () => {
        afterEach(() => {
            terminateDecompressionWorker()
        })

        it('getDecompressionWorkerManager returns singleton instance', () => {
            const instance1 = getDecompressionWorkerManager()
            const instance2 = getDecompressionWorkerManager()

            expect(instance1).toBe(instance2)
        })

        it('terminateDecompressionWorker cleans up singleton', () => {
            const instance1 = getDecompressionWorkerManager()
            terminateDecompressionWorker()
            const instance2 = getDecompressionWorkerManager()

            expect(instance1).not.toBe(instance2)
        })

        it('recreates instance when posthog config changes', () => {
            const mockPosthog1 = { capture: jest.fn() } as any
            const mockPosthog2 = { capture: jest.fn() } as any

            const instance1 = getDecompressionWorkerManager(mockPosthog1)
            const instance2 = getDecompressionWorkerManager(mockPosthog2)

            expect(instance1).not.toBe(instance2)
        })

        it('returns same instance when config has not changed', () => {
            const mockPosthog = { capture: jest.fn() } as any

            const instance1 = getDecompressionWorkerManager(mockPosthog)
            const instance2 = getDecompressionWorkerManager(mockPosthog)

            expect(instance1).toBe(instance2)
        })
    })
})
