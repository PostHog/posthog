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
                // In development, proxy worker through Django to avoid cross-origin issues
                // In production, Vite bundles workers properly

                // Use ?worker_file to get the actual worker URL directly (bypassing the wrapper)
                const workerUrl = new URL('./decompressionWorker.ts?worker_file&type=module', import.meta.url)

                // If the worker URL is cross-origin (different port), proxy it through Django
                const isDev = process.env.NODE_ENV === 'development'
                if (isDev && workerUrl.origin !== window.location.origin) {
                    const proxyPath = workerUrl.pathname + workerUrl.search
                    const actualWorkerUrl = `${window.location.origin}/_vite${proxyPath}`
                    this.worker = new Worker(actualWorkerUrl, { type: 'module' })
                } else {
                    this.worker = new Worker(workerUrl, { type: 'module' })
                }

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
