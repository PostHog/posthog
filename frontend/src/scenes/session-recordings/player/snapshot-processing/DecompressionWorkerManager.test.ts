import {
    DecompressionWorkerManager,
    getDecompressionWorkerManager,
    terminateDecompressionWorker,
} from './DecompressionWorkerManager'

// Faithful stand-in for the WASM decoder: return the bytes, but throw the way the real decode
// does when handed a detached buffer, so a re-detached fallback is observable in the test.
const mockDecompressRaw = jest.fn((data: Uint8Array): Uint8Array => {
    if (data.byteLength === 0) {
        throw new TypeError('attempting to access detached ArrayBuffer')
    }
    return data
})
jest.mock('snappy-wasm', () => ({
    __esModule: true,
    default: jest.fn().mockResolvedValue(undefined),
    decompress_raw: (data: Uint8Array) => mockDecompressRaw(data),
}))

// jest.setup.ts mocks this module globally with a no-op stand-in (to dodge import.meta.url in
// the worker chain); grab the real class to exercise the actual worker→main-thread fallback.
const RealDecompressionWorkerManager: typeof DecompressionWorkerManager =
    jest.requireActual('./DecompressionWorkerManager').DecompressionWorkerManager

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

    describe('main-thread fallback after worker failure', () => {
        const originalWorker = (global as any).Worker

        // Becomes ready, honors buffer transfer the way a real Worker does (transferring detaches
        // the caller's buffer), then reports a decode error to force the main-thread fallback.
        class FailingMockWorker {
            listeners: Record<string, ((event: any) => void)[]> = {}

            constructor() {
                setTimeout(() => this.emit('message', { data: { type: 'ready' } }), 0)
            }

            postMessage(message: any, options?: { transfer?: Transferable[] }): void {
                // Reproduce real transfer semantics: transferring a buffer detaches it on the caller's side.
                // ArrayBuffer.prototype.transfer (ES2024) does the detaching at runtime; cast since the app's
                // TS lib target predates it.
                for (const transferable of options?.transfer ?? []) {
                    if (transferable instanceof ArrayBuffer) {
                        ;(transferable as unknown as { transfer: () => void }).transfer()
                    }
                }
                setTimeout(() => this.emit('message', { data: { id: message.id, error: 'worker decode failed' } }), 0)
            }

            terminate(): void {}
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

        beforeEach(() => {
            mockDecompressRaw.mockClear()
            ;(global as any).Worker = FailingMockWorker
        })

        afterEach(() => {
            ;(global as any).Worker = originalWorker
        })

        it('recovers the bytes on the main thread and reports the real size when the worker fails', async () => {
            const capture = jest.fn()
            const manager = new RealDecompressionWorkerManager({ capture } as any)

            const data = new Uint8Array([1, 2, 3, 4, 5])
            // Transferring the buffer (the bug) detaches our copy, so the fallback would decode an
            // empty array and throw; keeping the copy lets the main-thread decode return the bytes.
            await expect(manager.decompress(data)).resolves.toEqual(data)

            expect(mockDecompressRaw).toHaveBeenCalledTimes(1)
            expect(capture).toHaveBeenCalledWith(
                'replay_worker_decompression_failed',
                expect.objectContaining({ dataSize: data.length })
            )

            manager.terminate()
        })
    })

    describe('terminate', () => {
        it('terminates the manager successfully', () => {
            expect(() => manager.terminate()).not.toThrow()
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
            const mockPosthog1 = {} as any
            const mockPosthog2 = {} as any

            const instance1 = getDecompressionWorkerManager(mockPosthog1)
            const instance2 = getDecompressionWorkerManager(mockPosthog2)

            expect(instance1).not.toBe(instance2)
        })

        it('returns same instance when config has not changed', () => {
            const mockPosthog = {} as any

            const instance1 = getDecompressionWorkerManager(mockPosthog)
            const instance2 = getDecompressionWorkerManager(mockPosthog)

            expect(instance1).toBe(instance2)
        })
    })
})
