import type { PostHog } from 'posthog-js'
import snappyInit, { decompress_raw } from 'snappy-wasm'

import type { DecompressionRequest, DecompressionResponse } from './decompressionWorker'

interface PendingRequest {
    resolve: (data: Uint8Array) => void
    reject: (error: Error) => void
}

// Firefox can be noticeably slower than Chrome to fetch, compile and spin up a module
// worker on a cold cache, so give init generous headroom before declaring it failed.
// Chrome resolves near-instantly, so this only ever costs slower browsers on a genuine
// failure (where they would otherwise fall back to blocking main-thread decompression).
const WORKER_INIT_TIMEOUT_MS = 10000
const WORKER_DECOMPRESSION_TIMEOUT_MS = 10000
// A module worker that becomes ready and then crashes mid-session (e.g. WASM falling over
// in a worker context) is torn down and recreated rather than abandoning off-thread
// decompression for the rest of the session. Bounded so a browser that genuinely can't
// keep a worker alive doesn't thrash on every chunk.
const MAX_WORKER_RESTARTS = 2
// If the worker stays alive but keeps failing to decompress, stop paying the round-trip
// (and per-chunk telemetry) cost and decompress on the main thread directly.
const MAX_CONSECUTIVE_WORKER_FAILURES = 3

export class DecompressionWorkerManager {
    private snappyInitialized = false
    private worker: Worker | null = null
    private workerReady = false
    private workerDisabled = false
    private workerRestarts = 0
    private messageId = 0
    private pendingRequests = new Map<number, PendingRequest>()
    private initInFlight: Promise<void> | null = null
    private initFailureReported = false
    private consecutiveWorkerFailures = 0

    constructor(private readonly posthog?: PostHog) {
        // Warm the worker up eagerly so the first snapshot doesn't pay init latency, but
        // don't let init failures reject construction — they're handled internally.
        void this.ensureWorkerReady()
    }

    private getErrorMessage(error: unknown): string {
        return error instanceof Error ? error.message : 'Unknown error'
    }

    private async ensureWorkerReady(): Promise<void> {
        if (this.workerReady && this.worker) {
            return
        }
        if (this.workerDisabled) {
            return
        }
        if (this.initInFlight) {
            return this.initInFlight
        }
        this.initInFlight = this.initWorker().finally(() => {
            this.initInFlight = null
        })
        return this.initInFlight
    }

    private async initWorker(): Promise<void> {
        try {
            const worker = new Worker('/static/decompressionWorker.js', { type: 'module' })
            await this.waitForWorkerReady(worker)
            this.attachWorkerHandlers(worker)
            this.worker = worker
            this.workerReady = true
            this.consecutiveWorkerFailures = 0
        } catch (error) {
            this.handleInitFailure(error)
        }
    }

    private waitForWorkerReady(worker: Worker): Promise<void> {
        return new Promise<void>((resolve, reject) => {
            const cleanup = (): void => {
                clearTimeout(timeout)
                worker.removeEventListener('message', readyHandler)
                worker.removeEventListener('error', errorHandler)
            }
            const timeout = setTimeout(() => {
                cleanup()
                reject(new Error('Worker initialization timeout'))
            }, WORKER_INIT_TIMEOUT_MS)
            const readyHandler = (event: MessageEvent): void => {
                if (event.data?.type === 'ready') {
                    cleanup()
                    resolve()
                }
            }
            const errorHandler = (event: ErrorEvent): void => {
                cleanup()
                reject(new Error(event.message || 'Worker error during initialization'))
            }
            worker.addEventListener('message', readyHandler)
            worker.addEventListener('error', errorHandler)
        })
    }

    private attachWorkerHandlers(worker: Worker): void {
        worker.addEventListener('message', (event: MessageEvent) => {
            const data = event.data

            if (data && 'type' in data && data.type === 'ready') {
                return
            }

            const { id, decompressedData, error } = data as DecompressionResponse

            const pending = this.pendingRequests.get(id)
            if (!pending) {
                return
            }

            this.pendingRequests.delete(id)

            if (error || !decompressedData) {
                pending.reject(new Error(error || 'Decompression failed'))
            } else {
                pending.resolve(decompressedData)
            }
        })

        worker.addEventListener('error', (error) => {
            // A worker that errors after becoming ready must be torn down: otherwise
            // shouldUseWorker() keeps routing chunks to a dead worker, each stalling for the
            // full decompression timeout before falling back. Recreate it (bounded) so
            // off-thread decompression can resume instead of freezing the rest of the session.
            console.error('[DecompressionWorkerManager] Worker error:', error)
            this.rejectPendingRequests(`Worker error: ${error.message}`)
            this.teardownWorker()
            if (this.workerRestarts >= MAX_WORKER_RESTARTS) {
                this.workerDisabled = true
            } else {
                this.workerRestarts++
            }
        })
    }

    private handleInitFailure(error: unknown): void {
        console.error('[DecompressionWorkerManager] Failed to initialize worker, will fallback to main thread:', error)
        this.teardownWorker()
        this.workerDisabled = true
        void this.initSnappy().catch(() => {
            // Surfaced on the actual decompression call; nothing useful to do with a warm-up failure here
        })
        if (this.posthog && !this.initFailureReported) {
            this.initFailureReported = true
            this.posthog.capture('replay_worker_init_failed', {
                error: this.getErrorMessage(error),
            })
        }
    }

    private teardownWorker(): void {
        this.workerReady = false
        if (this.worker) {
            this.worker.terminate()
            this.worker = null
        }
    }

    private rejectPendingRequests(message: string): void {
        this.pendingRequests.forEach((pending) => {
            pending.reject(new Error(message))
        })
        this.pendingRequests.clear()
    }

    private async initSnappy(): Promise<void> {
        if (this.snappyInitialized) {
            return
        }
        await snappyInit()
        this.snappyInitialized = true
    }

    async decompress(compressedData: Uint8Array): Promise<Uint8Array> {
        await this.ensureWorkerReady()

        if (this.shouldUseWorker()) {
            return this.decompressWithFallback(compressedData)
        }
        return this.decompressMainThread(compressedData)
    }

    private shouldUseWorker(): boolean {
        return this.worker !== null && this.workerReady && !this.workerDisabled
    }

    private async decompressWithFallback(compressedData: Uint8Array): Promise<Uint8Array> {
        try {
            const result = await this.decompressWithWorker(compressedData)
            this.consecutiveWorkerFailures = 0
            return result
        } catch (error) {
            this.reportWorkerFailure(error, compressedData.length)
            return this.decompressMainThread(compressedData)
        }
    }

    private reportWorkerFailure(error: unknown, dataSize: number): void {
        console.warn('[DecompressionWorkerManager] Worker decompression failed, falling back to main thread:', error)
        this.consecutiveWorkerFailures++
        if (this.posthog) {
            this.posthog.capture('replay_worker_decompression_failed', {
                error: this.getErrorMessage(error),
                dataSize,
            })
        }
        if (this.consecutiveWorkerFailures >= MAX_CONSECUTIVE_WORKER_FAILURES) {
            // The worker can't reliably decompress on this browser — stop routing chunks
            // through it and use the main thread directly from here on.
            this.workerDisabled = true
            this.teardownWorker()
        }
    }

    private async decompressWithWorker(compressedData: Uint8Array): Promise<Uint8Array> {
        const id = this.messageId++

        return new Promise<Uint8Array>((resolve, reject) => {
            // Timeout safeguard: if worker doesn't respond, reject and fallback
            const timeout = setTimeout(() => {
                const pending = this.pendingRequests.get(id)
                if (pending) {
                    this.pendingRequests.delete(id)
                    console.error('[DecompressionWorkerManager] Worker decompression timeout', {
                        id,
                        dataSize: compressedData.length,
                        timeoutMs: WORKER_DECOMPRESSION_TIMEOUT_MS,
                    })
                    reject(new Error('Worker decompression timeout'))
                }
            }, WORKER_DECOMPRESSION_TIMEOUT_MS)

            this.pendingRequests.set(id, {
                resolve: (data) => {
                    clearTimeout(timeout)
                    resolve(data)
                },
                reject: (error) => {
                    clearTimeout(timeout)
                    reject(error)
                },
            })

            const message: DecompressionRequest = {
                id,
                compressedData,
            }

            try {
                this.worker!.postMessage(message, { transfer: [compressedData.buffer] })
            } catch (error) {
                clearTimeout(timeout)
                this.pendingRequests.delete(id)
                reject(error instanceof Error ? error : new Error(this.getErrorMessage(error)))
            }
        })
    }

    private async decompressMainThread(compressedData: Uint8Array): Promise<Uint8Array> {
        try {
            await this.initSnappy()
            return decompress_raw(compressedData)
        } catch (error) {
            console.error('Decompression error:', error)
            throw error instanceof Error ? error : new Error('Unknown decompression error')
        }
    }

    terminate(): void {
        this.teardownWorker()
        this.rejectPendingRequests('Worker terminated')
    }
}

let workerManager: DecompressionWorkerManager | null = null
let currentPosthog: PostHog | undefined

export function getDecompressionWorkerManager(posthog?: PostHog): DecompressionWorkerManager {
    const configChanged = currentPosthog !== posthog

    if (configChanged && workerManager) {
        terminateDecompressionWorker()
    }

    if (!workerManager) {
        workerManager = new DecompressionWorkerManager(posthog)
        currentPosthog = posthog
    }
    return workerManager
}

export function terminateDecompressionWorker(): void {
    if (workerManager) {
        workerManager.terminate()
        workerManager = null
    }
    currentPosthog = undefined
}

/**
 * Pre-warm the WASM decompression module.
 * Call this during app initialization to avoid cold start penalty.
 * Safe to call multiple times - will only initialize once.
 */
export function preWarmDecompression(): void {
    // Initialize WASM module in background
    // Don't await - let it warm up while app loads
    snappyInit().catch((error) => {
        console.error('[DecompressionWorkerManager] Failed to pre-warm WASM:', error)
    })
}
