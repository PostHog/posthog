import { BlackholeSessionBatchWriter } from './blackhole-session-batch-writer'

jest.setTimeout(1000)

describe('BlackholeSessionBatchWriter', () => {
    let writer: BlackholeSessionBatchWriter

    beforeEach(() => {
        writer = new BlackholeSessionBatchWriter()
    })

    it('should create a writable stream', () => {
        const { stream } = writer.newBatch()
        expect(stream.writable).toBe(true)
    })

    it('should drain the stream', async () => {
        const { stream } = writer.newBatch()
        const largeData = Buffer.alloc(1024 * 1024, 'x') // 1MB of data

        // Write 100MB of data
        for (let i = 0; i < 5; i++) {
            let canWrite = true
            while (canWrite) {
                canWrite = stream.write(largeData)
                if (!canWrite) {
                    // Handle backpressure by waiting for drain event
                    await new Promise<void>((resolve) => stream.once('drain', resolve))
                }
            }
        }
    })

    it('should resolve finish immediately', async () => {
        const { stream, finish } = writer.newBatch()

        // Write some data before finishing
        stream.write('test data')
        stream.end()

        const startTime = Date.now()
        await finish()
        const duration = Date.now() - startTime

        // finish() should resolve almost immediately
        expect(duration).toBeLessThan(100) // Should take less than 100ms
    })

    it('should handle multiple writes and end correctly', async () => {
        const { stream, finish } = writer.newBatch()

        const writes = ['data1', 'data2', 'data3'].map((data) => {
            return new Promise<void>((resolve, reject) => {
                stream.write(data, (error) => {
                    if (error) {
                        reject(error)
                    } else {
                        resolve()
                    }
                })
            })
        })

        await Promise.all(writes)
        stream.end()
        await finish()
    })
})
