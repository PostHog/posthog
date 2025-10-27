import type { EncodedRecordingSnapshot, RecordingSnapshot } from '~/types'

import { parseEncodedSnapshotsImpl } from './process-all-snapshots'
import type { ParseSnapshotsRequest, WorkerError, WorkerResponse } from './snapshotProcessingWorkerTypes'

export class SnapshotProcessingWorkerManager {
    private worker: Worker | null = null
    private requestId = 0
    private pendingRequests = new Map<
        string,
        {
            resolve: (snapshots: RecordingSnapshot[]) => void
            reject: (error: Error) => void
        }
    >()

    async initialize(): Promise<void> {
        if (this.worker) {
            return
        }

        try {
            const workerUrl = '/static/snapshotProcessingWorker.js'
            this.worker = new Worker(workerUrl, { type: 'module' })

            this.worker.addEventListener('message', (event: MessageEvent<WorkerResponse | WorkerError>) => {
                const response = event.data

                if (response.type === 'error') {
                    const pending = this.pendingRequests.get(response.id)
                    if (pending) {
                        pending.reject(new Error(response.error))
                        this.pendingRequests.delete(response.id)
                    }
                    return
                }

                if (response.type === 'parse-snapshots-response') {
                    const pending = this.pendingRequests.get(response.id)
                    if (pending) {
                        pending.resolve(response.snapshots)
                        this.pendingRequests.delete(response.id)
                    }
                    return
                }
            })

            this.worker.addEventListener('error', (error) => {
                console.error('[SnapshotProcessingWorkerManager] Worker error:', error)
            })
        } catch (error) {
            console.error('[SnapshotProcessingWorkerManager] Failed to initialize worker:', error)
            throw error
        }
    }

    async parseEncodedSnapshots(
        items: (RecordingSnapshot | EncodedRecordingSnapshot | string)[] | ArrayBuffer | Uint8Array,
        sessionId: string
    ): Promise<RecordingSnapshot[]> {
        if (!this.worker) {
            console.warn('[SnapshotProcessingWorkerManager] Worker not initialized, falling back to main thread')
            return parseEncodedSnapshotsImpl(items, sessionId)
        }

        const id = `parse-${++this.requestId}`

        return new Promise<RecordingSnapshot[]>((resolve, reject) => {
            this.pendingRequests.set(id, { resolve, reject })

            const request: ParseSnapshotsRequest = {
                type: 'parse-snapshots',
                id,
                items,
                sessionId,
            }

            this.worker!.postMessage(request)
        })
    }

    terminate(): void {
        if (this.worker) {
            this.worker.terminate()
            this.worker = null
        }

        this.pendingRequests.forEach(({ reject }) => {
            reject(new Error('Worker terminated'))
        })
        this.pendingRequests.clear()
    }
}

let workerManager: SnapshotProcessingWorkerManager | null = null

export function getSnapshotProcessingWorkerManager(): SnapshotProcessingWorkerManager {
    if (!workerManager) {
        workerManager = new SnapshotProcessingWorkerManager()
    }
    return workerManager
}

export function terminateSnapshotProcessingWorker(): void {
    if (workerManager) {
        workerManager.terminate()
        workerManager = null
    }
}
