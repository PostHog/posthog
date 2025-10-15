import type { DecompressionResponse } from './decompressionWorker'

export class DecompressionWorkerManager {
    private worker: Worker | null = null
    private nextRequestId = 0
    private pendingRequests = new Map<number, { resolve: (data: Uint8Array) => void; reject: (error: Error) => void }>()
    private readonly readyPromise: Promise<void>

    constructor() {
        this.readyPromise = this.initWorker()
    }

    private async initWorker(): Promise<void> {
        return new Promise((resolve, reject) => {
            try {
                // Detect file extension based on current module
                // In dev: DecompressionWorkerManager.ts -> decompressionWorker.ts
                // In prod: DecompressionWorkerManager-[hash].js -> decompressionWorker-[hash].js
                const currentUrl = import.meta.url
                const extension = currentUrl.includes('.ts') ? 'ts' : 'js'
                const workerUrl = new URL(`./decompressionWorker.${extension}?worker_file&type=module`, import.meta.url)
                const js = `import ${JSON.stringify(workerUrl.href)}`
                // Use blob workaround for cross-origin worker loading in development
                // See: https://github.com/vitejs/vite/issues/13680
                const blob = new Blob([js], { type: 'application/javascript' })
                const objURL = URL.createObjectURL(blob)

                this.worker = new Worker(objURL, { type: 'module' })

                this.worker.addEventListener('error', () => {
                    URL.revokeObjectURL(objURL)
                })

                // Set up error listener to catch loading errors
                this.worker.addEventListener('error', (error) => {
                    console.error('Decompression worker error:', error)
                    reject(error)
                })

                // Add a timeout to detect if worker never sends ready signal
                const timeoutId = setTimeout(() => {
                    console.error('Worker initialization timeout - worker did not send ready signal')
                    reject(new Error('Worker initialization timeout - worker did not send ready signal'))
                }, 5000)

                this.worker.addEventListener('message', (event: MessageEvent) => {
                    if (event.data.type === 'ready') {
                        clearTimeout(timeoutId)
                        resolve()
                        return
                    }

                    const response = event.data as DecompressionResponse
                    const pending = this.pendingRequests.get(response.id)

                    if (pending) {
                        this.pendingRequests.delete(response.id)

                        if (response.error) {
                            console.error('Worker decompression error:', response.error)
                            pending.reject(new Error(response.error))
                        } else if (response.decompressedData) {
                            pending.resolve(response.decompressedData)
                        } else {
                            console.error('Worker returned no data and no error')
                            pending.reject(new Error('No data returned from worker'))
                        }
                    }
                })
            } catch (error) {
                console.error('Failed to initialize decompression worker:', error)
                reject(error)
            }
        })
    }

    async decompress(compressedData: Uint8Array): Promise<Uint8Array> {
        await this.readyPromise

        if (!this.worker) {
            throw new Error('Worker not initialized')
        }

        return new Promise((resolve, reject) => {
            const id = this.nextRequestId++
            this.pendingRequests.set(id, { resolve, reject })

            this.worker!.postMessage({ id, compressedData })
        })
    }

    terminate(): void {
        if (this.worker) {
            this.worker.terminate()
            this.worker = null
        }
        this.pendingRequests.clear()
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
