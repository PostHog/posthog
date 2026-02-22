import {
    DecompressionWorkerManager,
    decompressSnappy,
    getDecompressionWorkerManager,
    terminateDecompressionWorker,
} from './DecompressionWorkerManager'

jest.unmock('./DecompressionWorkerManager')
jest.mock('snappy-wasm')

describe('DecompressionWorkerManager', () => {
    describe('decompressSnappy', () => {
        it.each([
            { name: 'simple data', data: new Uint8Array([1, 2, 3, 4, 5]) },
            { name: 'empty data', data: new Uint8Array([]) },
        ])('decompresses $name successfully', async ({ data }) => {
            const result = await decompressSnappy(data)

            expect(result).toBeInstanceOf(Uint8Array)
            expect(result).toEqual(data)
        })

        it('handles multiple concurrent decompressions', async () => {
            const data1 = new Uint8Array([1, 2, 3])
            const data2 = new Uint8Array([4, 5, 6])
            const data3 = new Uint8Array([7, 8, 9])

            const [result1, result2, result3] = await Promise.all([
                decompressSnappy(data1),
                decompressSnappy(data2),
                decompressSnappy(data3),
            ])

            expect(result1).toEqual(data1)
            expect(result2).toEqual(data2)
            expect(result3).toEqual(data3)
        })
    })

    describe('processSnapshots', () => {
        let manager: DecompressionWorkerManager

        beforeEach(() => {
            manager = new DecompressionWorkerManager({} as any)
        })

        afterEach(() => {
            manager.terminate()
        })

        it('reports snapshot worker as available initially', () => {
            expect(manager.snapshotWorkerAvailable).toBe(true)
        })

        it('throws when snapshot worker is not available', async () => {
            const data = new Uint8Array([1, 2, 3])
            await expect(manager.processSnapshots(data, 'session-123')).rejects.toThrow()
        })
    })

    describe('singleton functions', () => {
        afterEach(() => {
            terminateDecompressionWorker()
        })

        it('returns null when posthog is not provided', () => {
            const instance = getDecompressionWorkerManager()
            expect(instance).toBeNull()
        })

        it('returns singleton instance when posthog is provided', () => {
            const mockPosthog = {} as any
            const instance1 = getDecompressionWorkerManager(mockPosthog)
            const instance2 = getDecompressionWorkerManager(mockPosthog)

            expect(instance1).toBe(instance2)
        })

        it('recreates instance when posthog reference changes', () => {
            const mockPosthog1 = {} as any
            const mockPosthog2 = {} as any

            const instance1 = getDecompressionWorkerManager(mockPosthog1)
            const instance2 = getDecompressionWorkerManager(mockPosthog2)

            expect(instance1).not.toBe(instance2)
        })

        it('terminateDecompressionWorker cleans up singleton', () => {
            const mockPosthog = {} as any
            const instance1 = getDecompressionWorkerManager(mockPosthog)
            terminateDecompressionWorker()
            const instance2 = getDecompressionWorkerManager(mockPosthog)

            expect(instance1).not.toBe(instance2)
        })
    })
})
