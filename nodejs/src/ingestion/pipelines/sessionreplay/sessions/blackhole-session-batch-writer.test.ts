import { BlackholeSessionBatchFileStorage } from './blackhole-session-batch-writer'

describe('BlackholeSessionBatchFileStorage', () => {
    let storage: BlackholeSessionBatchFileStorage
    let writer: ReturnType<BlackholeSessionBatchFileStorage['newBatch']>

    beforeEach(() => {
        storage = new BlackholeSessionBatchFileStorage()
        writer = storage.newBatch()
    })

    it('should write session data and return bytes written', async () => {
        const buffer = Buffer.from('test data')
        const result = await writer.writeSession({ buffer, teamId: 1, sessionId: '123' })

        expect(result.bytesWritten).toBe(buffer.length)
        expect(result.url).toBeNull()

        await expect(writer.finish()).resolves.not.toThrow()
    })

    it('should handle empty buffers', async () => {
        const buffer = Buffer.from('')
        const result = await writer.writeSession({ buffer, teamId: 1, sessionId: '123' })

        expect(result.bytesWritten).toBe(0)
        expect(result.url).toBeNull()

        await expect(writer.finish()).resolves.not.toThrow()
    })

    it('should handle large buffers', async () => {
        const buffer = Buffer.alloc(100 * 1024 * 1024, 'x') // 100MB of data
        const result = await writer.writeSession({ buffer, teamId: 1, sessionId: '123' })

        expect(result.bytesWritten).toBe(buffer.length)
        expect(result.url).toBeNull()

        await expect(writer.finish()).resolves.not.toThrow()
    })

    it('should handle multiple writes before finish', async () => {
        const buffer1 = Buffer.from('data1')
        const buffer2 = Buffer.from('data2')

        const result1 = await writer.writeSession({ buffer: buffer1, teamId: 1, sessionId: '123' })
        const result2 = await writer.writeSession({ buffer: buffer2, teamId: 2, sessionId: '321' })

        expect(result1.bytesWritten).toBe(buffer1.length)
        expect(result2.bytesWritten).toBe(buffer2.length)
        expect(result1.url).toBeNull()
        expect(result2.url).toBeNull()

        await expect(writer.finish()).resolves.not.toThrow()
    })
})
