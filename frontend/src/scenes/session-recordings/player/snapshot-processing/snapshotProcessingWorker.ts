import { parseEncodedSnapshotsImpl } from './process-all-snapshots'
import type { WorkerError, WorkerRequest, WorkerResponse } from './snapshotProcessingWorkerTypes'

self.addEventListener('message', async (event: MessageEvent<WorkerRequest>) => {
    const request = event.data

    try {
        switch (request.type) {
            case 'parse-snapshots': {
                const snapshots = await parseEncodedSnapshotsImpl(request.items, request.sessionId)
                const response: WorkerResponse = {
                    type: 'parse-snapshots-response',
                    id: request.id,
                    snapshots,
                }
                self.postMessage(response)
                break
            }
            default: {
                const error: WorkerError = {
                    type: 'error',
                    id: request.id,
                    error: `Unknown request type: ${(request as any).type}`,
                }
                self.postMessage(error)
            }
        }
    } catch (error) {
        const errorResponse: WorkerError = {
            type: 'error',
            id: request.id,
            error: error instanceof Error ? error.message : String(error),
        }
        self.postMessage(errorResponse)
    }
})
