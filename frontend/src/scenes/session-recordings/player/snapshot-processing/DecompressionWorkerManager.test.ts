import {
    DecompressionWorkerManager,
    getDecompressionWorkerManager,
    terminateDecompressionWorker,
} from './DecompressionWorkerManager'

const mockSnappyInit = jest.fn<Promise<void>, []>().mockResolvedValue(undefined)
const mockDecompressRaw = jest.fn((data: Uint8Array) => data)

jest.mock('snappy-wasm', () => ({
    __esModule: true,
    default: () => mockSnappyInit(),
    decompress_raw: (data: Uint8Array) => mockDecompressRaw(data),
}))

// The globally-mocked manager (jest.setup.ts) is a no-op stand-in; grab the real class to
// exercise the actual worker/WASM init failure handling.
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

    describe('worker init failure, main-thread WASM fallback', () => {
        const originalWorker = (global as any).Worker

        beforeEach(() => {
            mockSnappyInit.mockReset()
            mockDecompressRaw.mockReset().mockImplementation((data: Uint8Array) => data)
            // Force worker construction to fail so we drop into the main-thread fallback path.
            ;(global as any).Worker = jest.fn(() => {
                throw new Error('Worker unavailable')
            })
        })

        afterEach(() => {
            ;(global as any).Worker = originalWorker
        })

        it('falls back to the main thread and captures worker failure when snappy init succeeds', async () => {
            mockSnappyInit.mockResolvedValue(undefined)
            const capture = jest.fn()
            const fallbackManager = new RealDecompressionWorkerManager({ capture } as any)

            const data = new Uint8Array([1, 2, 3])
            await expect(fallbackManager.decompress(data)).resolves.toEqual(data)

            expect(capture).toHaveBeenCalledWith('replay_worker_init_failed', expect.any(Object))
            expect(capture).not.toHaveBeenCalledWith('replay_snappy_init_failed', expect.any(Object))
        })

        it('degrades cleanly and captures telemetry when the snappy WASM fetch also fails', async () => {
            // Mirror the transient network failure that used to escape as an uncaught rejection.
            mockSnappyInit.mockRejectedValue(new TypeError('Failed to fetch'))
            const capture = jest.fn()
            const fallbackManager = new RealDecompressionWorkerManager({ capture } as any)

            // readyPromise must settle (not reject uncaught), and decompress must fail cleanly.
            await expect(fallbackManager.decompress(new Uint8Array([1, 2, 3]))).rejects.toThrow(
                'Decompression unavailable'
            )

            expect(capture).toHaveBeenCalledWith('replay_worker_init_failed', expect.any(Object))
            expect(capture).toHaveBeenCalledWith('replay_snappy_init_failed', expect.any(Object))
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
