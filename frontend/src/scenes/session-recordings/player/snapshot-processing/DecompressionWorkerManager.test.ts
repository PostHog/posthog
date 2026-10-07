import snappyInit from 'snappy-wasm'

import {
    DecompressionWorkerManager,
    getDecompressionWorkerManager,
    terminateDecompressionWorker,
} from './DecompressionWorkerManager'

jest.mock('snappy-wasm', () => ({
    __esModule: true,
    default: jest.fn(() => Promise.resolve()),
    decompress_raw: jest.fn((data: Uint8Array) => data),
}))

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

    describe('when the worker and the main-thread fallback both fail to initialize', () => {
        it('records both failures and recovers once the fallback loads', async () => {
            const capture = jest.fn()
            const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
            jest.mocked(snappyInit)
                .mockRejectedValueOnce(new Error('wasm fetch failed'))
                .mockRejectedValueOnce(new Error('wasm fetch failed'))
            // jest.setup.ts mocks this module globally, so load the real implementation.
            const { DecompressionWorkerManager: RealManager } =
                jest.requireActual<typeof import('./DecompressionWorkerManager')>('./DecompressionWorkerManager')
            const failingManager = new RealManager({ capture } as any)

            await expect(failingManager.decompress(new Uint8Array([1]))).rejects.toThrow(
                'Could not load the snappy decompression module: wasm fetch failed'
            )
            expect(capture.mock.calls.map(([event]) => event)).toEqual([
                'replay_worker_init_failed',
                'replay_decompression_fallback_init_failed',
            ])

            await expect(failingManager.decompress(new Uint8Array([2]))).resolves.toEqual(new Uint8Array([2]))

            failingManager.terminate()
            consoleError.mockRestore()
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
