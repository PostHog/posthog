import {
    DecompressionWorkerManager,
    getDecompressionWorkerManager,
    terminateDecompressionWorker,
} from './DecompressionWorkerManager'

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

    describe('singleton functions', () => {
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
    })
})
