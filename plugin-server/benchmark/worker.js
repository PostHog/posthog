import { parentPort, workerData } from 'worker_threads'

import { Serializer } from './serializer.js'

const { workerId: _workerId, format } = workerData
const serializer = new Serializer(format)

parentPort.on('message', async (message) => {
    if (message.type === 'parse') {
        let successCount = 0
        const batch = message.data

        for (const line of batch) {
            try {
                if (format === 'protobuf') {
                    // For protobuf, read raw bytes
                    const buffer = Buffer.from(line, 'binary')
                    await serializer.deserialize(buffer)
                } else {
                    await serializer.deserialize(line)
                }
                successCount++
            } catch (error) {
                // Count as failed but continue processing batch
            }
        }

        // Respond with total count of successfully parsed messages
        parentPort.postMessage({ type: 'completed', count: successCount })
    }
})
