import type { DecompressionRequest, DecompressionResponse } from './decompressionWorker'

const DEBUG_VERSION_MANAGER = 'v25'

export class DecompressionWorkerManager {
    private worker: Worker | null = null
    private nextRequestId = 0
    private pendingRequests = new Map<number, { resolve: (data: Uint8Array) => void; reject: (error: Error) => void }>()
    private readyPromise: Promise<void>

    constructor() {
        console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Constructor called, creating new manager instance`)
        this.readyPromise = this.initWorker()
    }

    private async initWorker(): Promise<void> {
        console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Initializing decompression worker...`)
        return new Promise((resolve, reject) => {
            try {
                // In development, proxy worker through Django to avoid cross-origin issues
                // In production, Vite bundles workers properly
                console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Creating worker...`)

                // Use ?worker_file to get the actual worker URL directly (bypassing the wrapper)
                const workerUrl = new URL('./decompressionWorker.ts?worker_file&type=module', import.meta.url)

                // If the worker URL is cross-origin (different port), proxy it through Django
                const isDev = process.env.NODE_ENV === 'development'
                let actualWorkerUrl: string
                if (isDev && workerUrl.origin !== window.location.origin) {
                    const proxyPath = workerUrl.pathname + workerUrl.search
                    actualWorkerUrl = `${window.location.origin}/_vite${proxyPath}`
                    console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Using proxy URL:`, actualWorkerUrl)
                    this.worker = new Worker(actualWorkerUrl, { type: 'module' })
                } else {
                    actualWorkerUrl = workerUrl.href
                    this.worker = new Worker(workerUrl, { type: 'module' })
                }
                console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Worker instance created`)
                console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Worker URL:`, actualWorkerUrl)
                console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Setting up event listeners...`)

                // Set up error listener FIRST to catch loading errors
                this.worker.addEventListener('error', (error) => {
                    console.error(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Worker error event:`, error)
                    console.error(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Error details:`, {
                        message: error.message,
                        filename: error.filename,
                        lineno: error.lineno,
                        colno: error.colno,
                        error: error.error,
                        type: error.type,
                    })
                    if (error.error) {
                        console.error(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Error object:`, error.error)
                    }
                    reject(error)
                })

                // Add a timeout to detect if worker never sends ready signal
                const timeoutId = setTimeout(() => {
                    console.error(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Worker ready timeout after 5 seconds - worker may have failed to initialize`)
                    reject(new Error('Worker initialization timeout - worker did not send ready signal'))
                }, 5000)

                this.worker.addEventListener('message', (event: MessageEvent) => {
                    console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Received message from worker:`, event.data)
                    // Check for debug messages from worker
                    if (event.data.type === 'debug') {
                        console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Worker debug message:`, event.data.message)
                        return
                    }

                    // Check for ready signal
                    if (event.data.type === 'ready') {
                        console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Worker sent ready signal`)
                        clearTimeout(timeoutId)
                        resolve()
                        return
                    }

                    const response = event.data as DecompressionResponse
                    console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Worker response received:`, {
                        id: response.id,
                        hasData: !!response.decompressedData,
                        dataSize: response.decompressedData?.length,
                        hasError: !!response.error,
                    })
                    const pending = this.pendingRequests.get(response.id)

                    if (pending) {
                        this.pendingRequests.delete(response.id)

                        if (response.error) {
                            console.error(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Worker returned error:`, response.error)
                            pending.reject(new Error(response.error))
                        } else if (response.decompressedData) {
                            console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Worker decompression successful`)
                            pending.resolve(response.decompressedData)
                        } else {
                            console.error(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Worker returned no data and no error`)
                            pending.reject(new Error('No data returned from worker'))
                        }
                    } else {
                        console.warn(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Received response for unknown request ID:`, response.id)
                    }
                })
            } catch (error) {
                console.error(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Failed to initialize worker:`, error)
                reject(error)
            }
        })
    }

    async decompress(compressedData: Uint8Array): Promise<Uint8Array> {
        console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] decompress() called with data size:`, compressedData.length)
        console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Waiting for worker to be ready...`)
        // Wait for worker to be ready
        try {
            await this.readyPromise
            console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Worker is ready`)
        } catch (error) {
            console.error(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Worker readyPromise rejected:`, error)
            throw error
        }

        if (!this.worker) {
            console.error(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Worker not initialized`)
            throw new Error('Worker not initialized')
        }

        return new Promise((resolve, reject) => {
            const id = this.nextRequestId++
            console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Creating decompression request with ID:`, id)
            this.pendingRequests.set(id, { resolve, reject })

            const request: DecompressionRequest = {
                id,
                compressedData,
            }

            console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Posting message to worker...`)
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
    }
}

// Singleton instance - keyed by version to force recreation on code changes
let workerManager: DecompressionWorkerManager | null = null
let workerManagerVersion: string | null = null

export function getDecompressionWorkerManager(): DecompressionWorkerManager {
    // Force recreation if version changed (helps during development)
    if (workerManagerVersion !== DEBUG_VERSION_MANAGER) {
        console.log(`[DEBUG MANAGER ${DEBUG_VERSION_MANAGER}] Version changed from ${workerManagerVersion}, recreating manager...`)
        if (workerManager) {
            workerManager.terminate()
        }
        workerManager = null
        workerManagerVersion = DEBUG_VERSION_MANAGER
    }

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
