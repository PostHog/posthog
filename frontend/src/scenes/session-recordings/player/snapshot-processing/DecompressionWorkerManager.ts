import type { PostHog } from 'posthog-js'
import snappyInit, { decompress_raw } from 'snappy-wasm'

import type { RecordingSnapshot } from '~/types'

import type {
    SnapshotProcessingRequest,
    SnapshotProcessingResponse,
    WindowIdMapping,
} from './snapshot-processing-types'

export interface ProcessSnapshotsResult {
    snapshots: RecordingSnapshot[]
    windowIdMappings: WindowIdMapping[]
    metrics?: SnapshotProcessingResponse['metrics']
}

interface PendingSnapshotRequest {
    resolve: (result: ProcessSnapshotsResult) => void
    reject: (error: Error) => void
}

let snappyInitPromise: Promise<void> | null = null

function ensureSnappyInitialized(): Promise<void> {
    if (!snappyInitPromise) {
        snappyInitPromise = snappyInit().then(() => undefined)
    }
    return snappyInitPromise
}

export async function decompressSnappy(compressedData: Uint8Array): Promise<Uint8Array> {
    await ensureSnappyInitialized()
    return decompress_raw(compressedData)
}

export class DecompressionWorkerManager {
    private worker: Worker | null = null
    private workerReady: Promise<void> | null = null
    private workerInitFailed = false
    private messageId = 0
    private pendingRequests = new Map<number, PendingSnapshotRequest>()

    constructor(private readonly posthog: PostHog) {}

    private getErrorMessage(error: unknown): string {
        return error instanceof Error ? error.message : 'Unknown error'
    }

    private ensureWorker(): Promise<void> {
        if (this.workerReady) {
            return this.workerReady
        }
        this.workerReady = this.initWorker()
        return this.workerReady
    }

    private async initWorker(): Promise<void> {
        try {
            this.worker = new Worker('/static/snapshotProcessingWorker.js', { type: 'module' })

            const readyPromise = Promise.race([
                new Promise<void>((resolve) => {
                    const handler = (event: MessageEvent): void => {
                        if (event.data.type === 'ready') {
                            this.worker?.removeEventListener('message', handler)
                            resolve()
                        }
                    }
                    this.worker?.addEventListener('message', handler)
                }),
                new Promise<void>((_, reject) =>
                    setTimeout(() => reject(new Error('Worker initialization timeout')), 10000)
                ),
            ])

            this.worker.addEventListener('message', (event: MessageEvent) => {
                const data = event.data

                if ('type' in data && data.type === 'ready') {
                    return
                }

                const response = data as SnapshotProcessingResponse
                const pending = this.pendingRequests.get(response.id)
                if (!pending) {
                    return
                }

                this.pendingRequests.delete(response.id)

                if (response.error || !response.snapshots) {
                    pending.reject(new Error(response.error || 'Snapshot processing failed'))
                } else {
                    pending.resolve({
                        snapshots: response.snapshots,
                        windowIdMappings: response.windowIdMappings,
                        metrics: response.metrics,
                    })
                }
            })

            this.worker.addEventListener('error', (error) => {
                console.error('[DecompressionWorkerManager] Worker error:', error)
                this.pendingRequests.forEach((pending) => {
                    pending.reject(new Error(`Worker error: ${error.message}`))
                })
                this.pendingRequests.clear()
            })

            await readyPromise
        } catch (error) {
            console.error(
                '[DecompressionWorkerManager] Failed to initialize worker, will fallback to main thread:',
                error
            )
            this.workerInitFailed = true
            this.worker = null
            this.posthog.capture('replay_snapshot_worker_init_failed', {
                error: this.getErrorMessage(error),
            })
        }
    }

    async processSnapshots(compressedData: Uint8Array, sessionId: string): Promise<ProcessSnapshotsResult> {
        await this.ensureWorker()

        if (this.worker && !this.workerInitFailed) {
            return this.processSnapshotsWithWorker(compressedData, sessionId)
        }

        throw new Error('Snapshot processing worker not available')
    }

    get snapshotWorkerAvailable(): boolean {
        return !this.workerInitFailed
    }

    private processSnapshotsWithWorker(compressedData: Uint8Array, sessionId: string): Promise<ProcessSnapshotsResult> {
        const id = this.messageId++
        const PROCESSING_TIMEOUT_MS = 30000

        return new Promise<ProcessSnapshotsResult>((resolve, reject) => {
            const timeout = setTimeout(() => {
                const pending = this.pendingRequests.get(id)
                if (pending) {
                    this.pendingRequests.delete(id)
                    reject(new Error('Snapshot processing worker timeout'))
                }
            }, PROCESSING_TIMEOUT_MS)

            this.pendingRequests.set(id, {
                resolve: (result) => {
                    clearTimeout(timeout)
                    resolve(result)
                },
                reject: (error) => {
                    clearTimeout(timeout)
                    reject(error)
                },
            })

            const message: SnapshotProcessingRequest = {
                id,
                compressedData,
                sessionId,
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

    terminate(): void {
        if (this.worker) {
            this.worker.terminate()
            this.worker = null
        }

        this.pendingRequests.forEach((pending) => {
            pending.reject(new Error('Worker terminated'))
        })
        this.pendingRequests.clear()
    }
}

let workerManager: DecompressionWorkerManager | null = null
let currentPosthog: PostHog | undefined

export function getDecompressionWorkerManager(posthog?: PostHog): DecompressionWorkerManager | null {
    if (posthog && currentPosthog && posthog !== currentPosthog) {
        workerManager?.terminate()
        workerManager = null
    }
    if (!workerManager && posthog) {
        currentPosthog = posthog
        workerManager = new DecompressionWorkerManager(posthog)
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

export function preWarmDecompression(): void {
    ensureSnappyInitialized().catch((error) => {
        console.error('[DecompressionWorkerManager] Failed to pre-warm WASM:', error)
    })
}
