import type { DecompressionRequest, DecompressionResponse } from './decompressionWorker'

export class DecompressionWorkerManager {
    private worker: Worker | null = null
    private nextRequestId = 0
    private pendingRequests = new Map<number, { resolve: (data: Uint8Array) => void; reject: (error: Error) => void }>()
    private isReady = false
    private readyPromise: Promise<void>

    constructor() {
        this.readyPromise = this.initWorker()
    }

    private async initWorker(): Promise<void> {
        return new Promise((resolve, reject) => {
            try {
                // Create the worker - the build system should handle this
                this.worker = new Worker(new URL('./decompressionWorker.ts', import.meta.url), { type: 'module' })

                this.worker.addEventListener('message', (event: MessageEvent) => {
                    // Check for ready signal
                    if (event.data.type === 'ready') {
                        this.isReady = true
                        resolve()
                        return
                    }

                    const response = event.data as DecompressionResponse
                    const pending = this.pendingRequests.get(response.id)

                    if (pending) {
                        this.pendingRequests.delete(response.id)

                        if (response.error) {
                            pending.reject(new Error(response.error))
                        } else if (response.decompressedData) {
                            pending.resolve(response.decompressedData)
                        } else {
                            pending.reject(new Error('No data returned from worker'))
                        }
                    }
                })

                this.worker.addEventListener('error', (error) => {
                    console.error('Decompression worker error:', error)
                    reject(error)
                })
            } catch (error) {
                reject(error)
            }
        })
    }

    async decompress(compressedData: Uint8Array): Promise<Uint8Array> {
        // Wait for worker to be ready
        await this.readyPromise

        if (!this.worker) {
            throw new Error('Worker not initialized')
        }

        return new Promise((resolve, reject) => {
            const id = this.nextRequestId++
            this.pendingRequests.set(id, { resolve, reject })

            const request: DecompressionRequest = {
                id,
                compressedData,
            }

            this.worker!.postMessage(request)
        })
    }

    /**
     * Decompress multiple blocks in parallel
     */
    async decompressBatch(compressedBlocks: Uint8Array[]): Promise<Uint8Array[]> {
        return Promise.all(compressedBlocks.map((block) => this.decompress(block)))
    }

    terminate(): void {
        if (this.worker) {
            this.worker.terminate()
            this.worker = null
        }
        this.pendingRequests.clear()
        this.isReady = false
    }
}

// Singleton instance
let workerManager: DecompressionWorkerManager | null = null

export function getDecompressionWorkerManager(): DecompressionWorkerManager {
    if (!workerManager) {
        workerManager = new DecompressionWorkerManager()
    }
    return workerManager
}

export function terminateDecompressionWorker(): void {
    if (workerManager) {
        workerManager.terminate()
        workerManager = null
    }
}
