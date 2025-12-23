/**
 * Test worker for worker-manager tests.
 * Simulates a simple echo worker that returns results for events.
 */
import { MessagePort, workerData } from 'worker_threads'

import { MainToWorkerMessage, WorkerResultType } from './serializable'

const { port } = workerData as { config: any; port: MessagePort }

port.on('message', (msg: MainToWorkerMessage) => {
    switch (msg.type) {
        case 'event': {
            // Echo back the data as an OK result
            port.postMessage({
                type: 'result',
                result: {
                    type: WorkerResultType.OK,
                    correlationId: msg.correlationId,
                    value: msg.data,
                    warnings: [],
                },
            })
            break
        }
        case 'flush': {
            port.postMessage({ type: 'flush_complete' })
            break
        }
        case 'shutdown': {
            process.exit(0)
        }
    }
})

// Keep port referenced to prevent event loop from exiting
port.ref()

// Signal ready
port.postMessage({ type: 'ready' })
