import snappy from 'snappy'

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
        it('decompresses snappy-compressed data successfully', async () => {
            const originalData = Buffer.from('Hello, World!')
            const compressedData = await snappy.compress(originalData)
            const result = await manager.decompress(compressedData)

            expect(result).toBeInstanceOf(Uint8Array)
            expect(Buffer.from(result).toString()).toBe('Hello, World!')
        })

        it('handles multiple sequential decompressions', async () => {
            const data1 = await snappy.compress(Buffer.from('test1'))
            const data2 = await snappy.compress(Buffer.from('test2'))
            const data3 = await snappy.compress(Buffer.from('test3'))

            const result1 = await manager.decompress(data1)
            const result2 = await manager.decompress(data2)
            const result3 = await manager.decompress(data3)

            expect(Buffer.from(result1).toString()).toBe('test1')
            expect(Buffer.from(result2).toString()).toBe('test2')
            expect(Buffer.from(result3).toString()).toBe('test3')
        })

        it('handles multiple concurrent decompressions', async () => {
            const data1 = await snappy.compress(Buffer.from('test1'))
            const data2 = await snappy.compress(Buffer.from('test2'))
            const data3 = await snappy.compress(Buffer.from('test3'))

            const [result1, result2, result3] = await Promise.all([
                manager.decompress(data1),
                manager.decompress(data2),
                manager.decompress(data3),
            ])

            expect(Buffer.from(result1).toString()).toBe('test1')
            expect(Buffer.from(result2).toString()).toBe('test2')
            expect(Buffer.from(result3).toString()).toBe('test3')
        })
    })

    describe('decompressBatch', () => {
        it('decompresses multiple blocks in parallel', async () => {
            const blocks = await Promise.all([
                snappy.compress(Buffer.from('block1')),
                snappy.compress(Buffer.from('block2')),
                snappy.compress(Buffer.from('block3')),
            ])

            const results = await manager.decompressBatch(blocks)

            expect(results).toHaveLength(3)
            expect(Buffer.from(results[0]).toString()).toBe('block1')
            expect(Buffer.from(results[1]).toString()).toBe('block2')
            expect(Buffer.from(results[2]).toString()).toBe('block3')
        })

        it('handles empty batch', async () => {
            const results = await manager.decompressBatch([])
            expect(results).toHaveLength(0)
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
