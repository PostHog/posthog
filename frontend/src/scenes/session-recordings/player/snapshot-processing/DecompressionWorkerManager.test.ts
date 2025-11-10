import {
    type DecompressionMode,
    DecompressionWorkerManager,
    getDecompressionWorkerManager,
    terminateDecompressionWorker,
} from './DecompressionWorkerManager'

jest.mock('snappy-wasm')

describe('DecompressionWorkerManager', () => {
    describe.each([
        ['blocking mode', 'blocking' as DecompressionMode],
        ['yielding mode', 'yielding' as DecompressionMode],
        // Worker mode requires a real browser environment with Worker support
        // Skip for now since Jest runs in Node.js environment
        // ['worker mode', 'worker' as DecompressionMode],
    ])('%s', (_modeName, mode) => {
        let manager: DecompressionWorkerManager

        beforeEach(() => {
            manager = new DecompressionWorkerManager(mode)
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

        describe('stats', () => {
            it('tracks decompression stats', async () => {
                const data = new Uint8Array([1, 2, 3, 4, 5])
                await manager.decompress(data)
                await manager.decompress(data)

                const stats = manager.getStats()

                expect(stats.count).toBe(2)
                expect(stats.totalSize).toBe(10)
                expect(stats.totalTime).toBeGreaterThan(0)
            })
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

        it('recreates instance when mode config changes', () => {
            const instance1 = getDecompressionWorkerManager('blocking')
            const instance2 = getDecompressionWorkerManager('yielding')

            expect(instance1).not.toBe(instance2)
        })

        it('recreates instance when posthog config changes', () => {
            const mockPosthog1 = {} as any
            const mockPosthog2 = {} as any

            const instance1 = getDecompressionWorkerManager('blocking', mockPosthog1)
            const instance2 = getDecompressionWorkerManager('blocking', mockPosthog2)

            expect(instance1).not.toBe(instance2)
        })

        it('returns same instance when config has not changed', () => {
            const mockPosthog = {} as any

            const instance1 = getDecompressionWorkerManager('blocking', mockPosthog)
            const instance2 = getDecompressionWorkerManager('blocking', mockPosthog)

            expect(instance1).toBe(instance2)
        })
    })
})
